# app/

FastAPI application package. The only active entry point from the client is `POST /api/v1/messages/webhook`.

## Request lifecycle

```
Client  →  POST /api/v1/messages/webhook
              │
              ├─ auth: verify X-API-Key header
              │
              ├─ MessageService.store_webhook_content()
              │     upserts Groups, Users, Members, Questions,
              │     GroupQuestions, Messages from payload
              │
              ├─ returns 200 immediately
              │
              └─ [background task] process_facilitation_background()
                    │
                    ├─ determines target threads:
                    │     • active threads in payload whose last message is not AI
                    │     • 5% random sample of all other active threads
                    │
                    └─ FacilitationService._process_thread() per thread
                          │
                          └─ FacilitationDecisionPipeline.run_pipeline()
                                ├─ Stage 1: Random Forest on temporal features
                                ├─ Stage 2: LLM zero-shot verification (gpt-5-mini)
                                ├─ Stage 3: LLM message generation (gpt-4.1)
                                └─ Stage 4: LLM red-flag check (gpt-5-mini)
                                      → if FACILITATE: WebhookClient POSTs to app
```

`bypass=true` in the request body forces the pipeline to always reach stage 3/4 (for testing).

---

## Files

### `main.py`
FastAPI app setup. On startup: initializes the DB and loads the Random Forest model into `app.state.pipeline` (shared across all background tasks). Active routers: `health`, `messages`. The `facilitation` router is commented out.

### `config.py`
`Settings` loaded from `.env` via Pydantic Settings. Key values:
- `OPENAI_API_KEY` — required
- `API_KEY` — for `X-API-Key` auth
- `APPLICATION_WEBHOOK_URL` — where facilitation responses are sent
- `STAGE_2_MODEL`, `STAGE_3_MODEL`, `STAGE_4_MODEL` — per-stage OpenAI model names
- `MIN_MESSAGES` — minimum messages in thread before running pipeline
- `LIMIT_MESSAGES` — how many recent messages to pass to pipeline (default 20)

Also configures logging: JSON format in production, plain text in development.

---

## `api/`

### `api/middleware/auth.py`
`verify_api_key` FastAPI dependency. Reads `X-API-Key` header, compares to `settings.api_key`. Returns 401 if missing, 403 if wrong.

### `api/routes/health.py`
`GET /health` — no auth, returns `{"status": "healthy", ...}`. Used for uptime monitoring.

### `api/routes/messages.py`
All active endpoints live here:

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/messages/webhook` | **Main endpoint.** Store messages + trigger facilitation in background. |
| `POST /api/v1/messages/save` | Store-only variant (no facilitation). Likely legacy/debug. |
| `GET /api/v1/messages/logs` | Fetch stored messages for a group by `group_id`. |
| `PATCH /api/v1/messages/group_activity` | Set a group's `is_active` flag. |

---

## `models/`

### `models/database.py`
SQLAlchemy ORM models. All tables:

| Model | Table | Description |
|---|---|---|
| `Group` | `groups` | A chat group. Has `external_id` (from client), `is_active`. |
| `User` | `users` | A user across all groups. Identified by `external_user_id`. |
| `Member` | `members` | Join table: User ↔ Group membership. |
| `Question` | `questions` | A discussion prompt (global, shared across groups). |
| `QuestionOption` | `question_options` | Possible answer categories for a Question. |
| `GroupQuestion` | `group_questions` | A question thread within a group. `status` field: `active`/`expired`/`pending`. |
| `Message` | `messages` | A message in a GroupQuestion thread. `is_ai=True` marks AI messages. |
| `FacilitationLog` | `facilitation_logs` | One record per pipeline run. Stores per-stage JSON results and final decision. |

`FacilitationDecision` enum: `NO_FACILITATION`, `NO_FACILITATION_AFTER_VERIFY`, `FACILITATE`.

Also exports `get_db()`, `AsyncSessionLocal`, `init_db()`.

### `models/schemas.py`
Pydantic models for request/response validation. Key schemas:

- **Incoming webhook:** `WebhookIncomingRequest` → `WebhookIncomingPayload` → `WebhookIncomingGroup` → `WebhookIncomingThread` → `WebhookIncomingMessage`
- **Outgoing facilitation:** `FacilitationBatchMessagesResponse` containing `FacilitationMessageResponse` (group_id, question_id, content)
- **Endpoint responses:** `WebhookResponse`, `GroupUpdateResponse`, `MessageResponse`, `HealthCheckResponse`
- Several unused schemas (`ConversationHistoryResponse`, `FacilitationCheckRequest/Response`) left from the disabled facilitation router.

---

## `services/`

### `services/message_service.py` — `MessageService`
All DB read/write logic. Accepts an `AsyncSession`. Key methods:

- `store_webhook_content(request)` — full upsert of everything in a webhook payload (groups, users, members, questions, threads, messages). Syncs `is_active` from `groups_metadata`.
- `get_or_create_{user,group,member,question,group_question}()` — idempotent upserts.
- `get_conversation_history(group, group_question, limit)` — returns messages for a thread, most recent `limit` messages.
- `get_active_group_questions_not_in(exclude_pairs)` — used to find the random 5% sample of other active threads.
- `create_facilitation_log(...)` — writes pipeline results to `facilitation_logs`.

### `services/facilitation_service.py` — `FacilitationService`
Orchestrates pipeline execution across threads. Takes a `session` and a `FacilitationDecisionPipeline`.

- `process_webhook_messages(pairs, bypass)` — iterates pairs, calls `_process_thread` for each, collects responses.
- `_process_thread(group_id, question_id, bypass)` — loads messages, calls `pipeline.run_pipeline()`, writes the facilitation log, returns response dict if `FACILITATE`.

### `services/webhook_client.py` — `WebhookClient`
Sends facilitation results back to the client app via HTTP POST to `{APPLICATION_WEBHOOK_URL}/api/ai/facilitation`. Includes exponential backoff retry (3 attempts). Does not retry on 4xx errors. Uses `Authorization: Bearer <api_key>` header.

### `services/facilitator/pipeline.py` — `FacilitationDecisionPipeline`
Runs all four stages in sequence with early exit. Loaded once at startup and reused.

- **Stage 1** (`stage1_temporal_classification`): Runs `TemporalFeatureExtractor` then Random Forest. Exits pipeline if `should_facilitate=False`.
- **Stage 2** (`stage2_llm_verification`): Asks LLM if facilitation is needed. Exits with `NO_FACILITATION_AFTER_VERIFY` if not.
- **Stage 3** (`stage3_generate_facilitation`): Generates the facilitation message. Includes `red_flag_feedback` on retry attempts.
- **Stage 4** (`stage4_verify_red_flags`): Checks generated message for red flags. Loops back to Stage 3 up to `max_regeneration_attempts` (default 2) if `recommendation != "approve"`.

All LLM calls use `retry_with_exponential_backoff` (3 retries). In `bypass=True` mode, stage failures default to "proceed" and negative decisions are ignored.

### `services/facilitator/feature_extractor.py` — `TemporalFeatureExtractor`
Extracts 5 temporal features from a message list for Stage 1:
`messages_last_30min`, `messages_last_hour`, `messages_last_3hours`, `avg_gap_last_5_messages_min`, `time_since_last_message_min`.

### `services/facilitator/llm_service.py` — `LLMService`
Wraps OpenAI API calls for stages 2, 3, 4. Each stage method returns structured JSON parsed from the response. Also has `format_conversation()` to format a message list into a readable string for the LLM.

### `services/facilitator/prompts.py`
All LLM prompt templates (system and user prompts for each stage).
