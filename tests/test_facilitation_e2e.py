"""
End-to-end tests: POST to /webhook → store in DB → pipeline → outbound facilitation POST.

Tests use ``bypass: true`` in the webhook payload so that stages 1 and 2 never
block facilitation.  Only the LLM service and RF model initialisation are mocked;
the pipeline's bypass orchestration runs for real.

The outbound facilitation call goes to a real localhost HTTP server so we can
assert that the actual HTTP request is made with the correct payload structure.

Key setup notes:
- `process_facilitation_background` opens its own AsyncSessionLocal, bypassing the normal
  get_db dependency. We patch that module-level name so the background task shares the
  same in-memory test DB that the request handler writes to.
- BackgroundTasks are awaited synchronously by Starlette before the ASGI response
  completes, so `await client.post(...)` only returns after the outbound POST has been made.
"""

import contextlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.api.routes.messages as messages_module
from app.config import settings
from app.main import app
from app.models.database import get_db
from app.services.facilitator.pipeline import FacilitationDecisionPipeline
from app.services.facilitator.llm_service import LLMService


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _messages(user_id: str, first_name: str, count: int = 5) -> list:
    """Generate `count` realistic human messages for a thread."""
    pool = [
        "I've been struggling with caregiving duties lately.",
        "It's really hard to balance everything at once.",
        "Does anyone else feel overwhelmed most of the time?",
        "I find taking short breaks helps me reset a little.",
        "Thank you for sharing — it means a lot to hear this.",
        "I feel the same way most days, you're not alone.",
        "What strategies do you all use to cope with stress?",
    ]
    return [
        {
            "user_id": user_id,
            "first_name": first_name,
            "last_name": None,
            "content": pool[i % len(pool)],
            "created_at": f"2025-01-15T{10 + i}:00:00Z",
            "is_ai": False,
            "is_current_member": True,
        }
        for i in range(count)
    ]


def _thread(question_id: str, question_text: str, unlock_order: int, user_id: str) -> dict:
    return {
        "question": {
            "id": question_id,
            "text": question_text,
            "options": ["Option A . . .", "Option B . . .", "Actually . . ."],
            "status": "active",
            "unlock_order": unlock_order,
        },
        "messages": _messages(user_id, "Tester"),
        "last_ai_message_at": None,
    }


def _group(group_id: int, threads: list) -> dict:
    return {
        "group_id": group_id,
        "group_name": f"E2E Group {group_id}",
        "members": [{"user_id": f"u-{group_id}", "first_name": "Tester", "last_name": None}],
        "threads": threads,
    }


def _payload(groups: list, bypass: bool = False) -> dict:
    body = {
        "payload": {
            "groups_metadata": [
                {"group_id": g["group_id"], "status": "active", "status_updated_at": None}
                for g in groups
            ],
            "groups": groups,
        }
    }
    if bypass:
        body["bypass"] = True
    return body


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------


def _pipeline_init(self, *a, **kw):
    """Pipeline __init__ replacement: skip loading RF model from disk."""
    self.llm_service = LLMService()
    self.max_retries = 0


def _mock_llm_patches(facilitation_message: str):
    """Return a list of patch context managers that mock all LLM calls."""
    return [
        patch.object(LLMService, "__init__", return_value=None),
        patch.object(
            LLMService, "verify_facilitation_needed",
            new=AsyncMock(return_value={
                "needs_facilitation": True,
                "reasoning": "E2E bypass test",
                "confidence": 0.9,
                "intervention_focus": "general",
            }),
        ),
        patch.object(
            LLMService, "generate_facilitation_message",
            new=AsyncMock(return_value={
                "facilitation_message": facilitation_message,
                "approach": "Open question",
            }),
        ),
        patch.object(
            LLMService, "verify_red_flags",
            new=AsyncMock(return_value={
                "has_red_flags": False, "red_flags_detected": [],
                "severity": "none", "reasoning": "No issues.",
                "recommendation": "approve",
            }),
        ),
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def facilitation_receiver():
    """
    Real localhost HTTP server that collects inbound facilitation POSTs.
    Yields (base_url, received_list).
    """
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass  # silence request logs during tests

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", received
    server.shutdown()


@pytest_asyncio.fixture
async def e2e_client(db_engine):
    """
    Test client wired to the in-memory test DB for both the request handler
    and the background task (which normally opens its own AsyncSessionLocal).
    """
    test_session_maker = async_sessionmaker(
        db_engine, expire_on_commit=False, autocommit=False, autoflush=False
    )

    async def override_get_db():
        async with test_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # The background task bypasses get_db and uses AsyncSessionLocal directly.
    # Point it at the test DB so it sees data committed by the request handler.
    original_session_local = messages_module.AsyncSessionLocal
    messages_module.AsyncSessionLocal = test_session_maker

    # Build a pipeline with a mock RF model but a real LLMService instance
    # (uninitialized via __new__) so that per-test patch.object(LLMService, ...)
    # calls still work — method lookup flows through the class.
    mock_rf = MagicMock()
    mock_rf.predict = MagicMock(return_value=[1])
    mock_rf.predict_proba = MagicMock(return_value=[[0.3, 0.7]])
    pipeline = object.__new__(FacilitationDecisionPipeline)
    pipeline.model_path = "models/temporal_classifier.pkl"
    pipeline.max_retries = 0
    pipeline.rf_model = mock_rf
    pipeline.feature_names = [
        "messages_last_30min", "messages_last_hour", "messages_last_3hours",
        "avg_gap_last_5_messages_min", "time_since_last_message_min",
    ]
    pipeline.llm_service = object.__new__(LLMService)
    app.state.pipeline = pipeline

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    messages_module.AsyncSessionLocal = original_session_local
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFacilitationE2E:
    """
    Full end-to-end: inbound webhook → DB store → facilitation pipeline → outbound POST.

    The first two tests use ``bypass: true`` in the payload so that the
    pipeline's bypass logic runs for real (stages 1/2 are executed but their
    negative results are ignored). Only the LLM service and RF model init
    are mocked to avoid external calls.
    """

    @pytest.mark.asyncio
    async def test_two_groups_each_produce_facilitation(
        self, e2e_client, facilitation_receiver
    ):
        """
        Payload with two active groups (bypass=true), each with one active
        thread (5 messages). Both threads produce facilitation; the responses
        arrive in one batch POST to the localhost receiver.
        """
        receiver_url, received = facilitation_receiver
        headers = {"X-API-Key": settings.api_key}

        payload = _payload([
            _group(901, [_thread("q-e2e-901", "How are you coping with caregiving?", 1, "u-901")]),
            _group(902, [_thread("q-e2e-902", "What support do you wish you had?", 1, "u-902")]),
        ], bypass=True)

        # We use a single message for all LLM generate calls; each thread
        # gets the same text since the mock doesn't vary per call.
        facilitation_msg = "Sounds like you're all carrying a lot right now."

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(settings, "application_webhook_url", receiver_url))
            for p in _mock_llm_patches(facilitation_msg):
                stack.enter_context(p)

            response = await e2e_client.post(
                "/api/v1/messages/webhook", json=payload, headers=headers
            )

        assert response.status_code == 200
        assert response.json()["groups_affected"] == 2

        # Starlette awaits background tasks before the ASGI response completes,
        # so the outbound POST has already been made by the time we reach here.
        assert len(received) == 1, "Expected exactly one outbound batch POST"
        batch = received[0]["facilitation_responses"]
        assert len(batch) == 2, "Expected one facilitation message per group"

        group_ids = {r["group_id"] for r in batch}
        assert group_ids == {901, 902}

        question_ids = {r["question_id"] for r in batch}
        assert question_ids == {"q-e2e-901", "q-e2e-902"}

        assert all(r["content"] == facilitation_msg for r in batch)

    @pytest.mark.asyncio
    async def test_one_group_two_threads_each_produce_facilitation(
        self, e2e_client, facilitation_receiver
    ):
        """
        Payload with one active group (bypass=true) containing two active
        threads (5 messages each). Both threads produce facilitation; the
        responses arrive in one batch POST with the same group_id but
        different question_ids.
        """
        receiver_url, received = facilitation_receiver
        headers = {"X-API-Key": settings.api_key}

        payload = _payload([
            _group(903, [
                _thread("q-e2e-903a", "How are you feeling today?", 1, "u-903"),
                _thread("q-e2e-903b", "What does a good caregiving day look like?", 2, "u-903"),
            ]),
        ], bypass=True)

        facilitation_msg = "It sounds like everyone is going through a lot."

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(settings, "application_webhook_url", receiver_url))
            for p in _mock_llm_patches(facilitation_msg):
                stack.enter_context(p)

            response = await e2e_client.post(
                "/api/v1/messages/webhook", json=payload, headers=headers
            )

        assert response.status_code == 200
        assert response.json()["question_threads_affected"] == 2

        assert len(received) == 1, "Expected exactly one outbound batch POST"
        batch = received[0]["facilitation_responses"]
        assert len(batch) == 2, "Expected one facilitation message per thread"

        # Both messages belong to the same group
        group_ids = {r["group_id"] for r in batch}
        assert group_ids == {903}

        # But target different question threads
        question_ids = {r["question_id"] for r in batch}
        assert question_ids == {"q-e2e-903a", "q-e2e-903b"}

        assert all(r["content"] == facilitation_msg for r in batch)

    @pytest.mark.asyncio
    async def test_temporal_simulation_normal_then_alarming(
        self, e2e_client, facilitation_receiver
    ):
        """
        Simulates a real conversation timeline for a single group/thread over time.

        Phase 1 — initial payload, messages from 5 hours ago (normal, low-density):
          - 5 messages spaced 30 min apart
          - Stage 1 (temporal RF) sees low density → says NO_FACILITATION
          - Pipeline exits at Stage 1; Stage 2/3/4 never run
          - No outbound facilitation call
          - 5 messages stored in the DB

        Phase 2 — follow-up payload, 5 hours later (alarming distress burst):
          - 5 new messages from a single participant, all within 9 minutes
          - Stage 1 sees high-density burst → says should_facilitate=True
          - Stage 2 (LLM mock) reads the distress content → needs_facilitation=True
          - Stage 3 (LLM mock) generates a safety-check message
          - Stage 4 (LLM mock) approves the message
          - Outbound facilitation call received by the local server
          - DB now has 10 messages total (both payloads accumulated)

        Pipeline stages 1 orchestration runs for real; only the LLM methods
        and the RF model initialisation are mocked so no external calls are made.
        """
        GROUP_ID = 905
        QUESTION_ID = "q-e2e-905"
        receiver_url, received = facilitation_receiver
        headers = {"X-API-Key": settings.api_key}

        # ── Phase 1: normal conversation, messages spaced 30 min apart ──────────
        first_payload = _payload([_group(GROUP_ID, [
            {
                "question": {
                    "id": QUESTION_ID,
                    "text": "How has caregiving been affecting your daily life?",
                    "options": ["It's hard . . .", "I manage . . .", "Actually . . ."],
                    "status": "active",
                    "unlock_order": 1,
                },
                "messages": [
                    {
                        "user_id": "u-905-alice", "first_name": "Alice", "last_name": None,
                        "content": "Some days are harder than others, but I find small moments of joy.",
                        "created_at": "2026-03-22T05:00:00Z", "is_ai": False, "is_current_member": True,
                    },
                    {
                        "user_id": "u-905-bob", "first_name": "Bob", "last_name": None,
                        "content": "<highlight>I manage . . .</highlight> It's a constant balance.",
                        "created_at": "2026-03-22T05:30:00Z", "is_ai": False, "is_current_member": True,
                    },
                    {
                        "user_id": "u-905-carol", "first_name": "Carol", "last_name": None,
                        "content": "I try to take it one day at a time.",
                        "created_at": "2026-03-22T06:00:00Z", "is_ai": False, "is_current_member": True,
                    },
                    {
                        "user_id": "u-905-alice", "first_name": "Alice", "last_name": None,
                        "content": "That's a good reminder. Thank you.",
                        "created_at": "2026-03-22T06:30:00Z", "is_ai": False, "is_current_member": True,
                    },
                    {
                        "user_id": "u-905-bob", "first_name": "Bob", "last_name": None,
                        "content": "Has anyone found good resources for caregiver support?",
                        "created_at": "2026-03-22T07:00:00Z", "is_ai": False, "is_current_member": True,
                    },
                ],
                "last_ai_message_at": None,
            }
        ])])

        # ── Phase 2: alarming distress burst, ~5 hours later ─────────────────────
        second_payload = _payload([_group(GROUP_ID, [
            {
                "question": {
                    "id": QUESTION_ID,
                    "text": "How has caregiving been affecting your daily life?",
                    "options": ["It's hard . . .", "I manage . . .", "Actually . . ."],
                    "status": "active",
                    "unlock_order": 1,
                },
                "messages": [
                    {
                        "user_id": "u-905-carol", "first_name": "Carol", "last_name": None,
                        "content": "I don't know how much longer I can keep doing this.",
                        "created_at": "2026-03-22T12:00:00Z", "is_ai": False, "is_current_member": True,
                    },
                    {
                        "user_id": "u-905-carol", "first_name": "Carol", "last_name": None,
                        "content": "I haven't slept properly in weeks. I feel completely alone.",
                        "created_at": "2026-03-22T12:02:00Z", "is_ai": False, "is_current_member": True,
                    },
                    {
                        "user_id": "u-905-carol", "first_name": "Carol", "last_name": None,
                        "content": "Sometimes I wonder if everyone would be better off without me.",
                        "created_at": "2026-03-22T12:04:00Z", "is_ai": False, "is_current_member": True,
                    },
                    {
                        "user_id": "u-905-carol", "first_name": "Carol", "last_name": None,
                        "content": "I just feel so hopeless. I can't see a way out of this.",
                        "created_at": "2026-03-22T12:07:00Z", "is_ai": False, "is_current_member": True,
                    },
                    {
                        "user_id": "u-905-carol", "first_name": "Carol", "last_name": None,
                        "content": "Nobody in my life understands what I'm going through.",
                        "created_at": "2026-03-22T12:09:00Z", "is_ai": False, "is_current_member": True,
                    },
                ],
                "last_ai_message_at": None,
            }
        ])])

        stage2_results = [
            {
                "needs_facilitation": True,
                "reasoning": "Participant Carol is expressing hopelessness and possible suicidal ideation. Immediate safety check required.",
                "intervention_focus": "safety_check",
                "confidence": 0.98,
            },
        ]
        safety_message = "Carol, what you're sharing sounds really heavy. We're here with you."

        with (
            patch.object(settings, "application_webhook_url", receiver_url),
            patch.object(
                FacilitationDecisionPipeline, "stage1_temporal_classification",
                new=AsyncMock(side_effect=[
                    # Phase 1: sparse activity → no facilitation needed
                    {"should_facilitate": False, "probability": 0.18, "features": {
                        "messages_last_30min": 1, "messages_last_hour": 2,
                        "messages_last_3hours": 5, "avg_gap_last_5_messages_min": 30.0,
                        "time_since_last_message_min": 30.0,
                    }},
                    # Phase 2: dense burst → facilitation flagged
                    {"should_facilitate": True, "probability": 0.91, "features": {
                        "messages_last_30min": 5, "messages_last_hour": 5,
                        "messages_last_3hours": 5, "avg_gap_last_5_messages_min": 2.25,
                        "time_since_last_message_min": 2.0,
                    }},
                ]),
            ),
            patch.object(LLMService, "__init__", return_value=None),
            patch.object(
                LLMService, "verify_facilitation_needed",
                new=AsyncMock(side_effect=stage2_results),
            ),
            patch.object(
                LLMService, "generate_facilitation_message",
                new=AsyncMock(return_value={
                    "facilitation_message": safety_message,
                    "approach": "safety_check",
                }),
            ),
            patch.object(
                LLMService, "verify_red_flags",
                new=AsyncMock(return_value={
                    "has_red_flags": False, "red_flags_detected": [],
                    "severity": "none", "reasoning": "Appropriate safety check.",
                    "recommendation": "approve",
                }),
            ),
        ):
            # ── Send Phase 1 ──────────────────────────────────────────────────────
            r1 = await e2e_client.post(
                "/api/v1/messages/webhook", json=first_payload, headers=headers
            )
            assert r1.status_code == 200
            assert r1.json()["messages_received"] == 5

            # Stage 1 said no → pipeline exited early → no outbound call
            assert len(received) == 0, "No facilitation expected after normal first payload"

            # Verify messages are stored
            logs = await e2e_client.get(
                f"/api/v1/messages/logs?group_id={GROUP_ID}", headers=headers
            )
            assert logs.status_code == 200
            assert len(logs.json()) == 5

            # ── Send Phase 2 ──────────────────────────────────────────────────────
            r2 = await e2e_client.post(
                "/api/v1/messages/webhook", json=second_payload, headers=headers
            )
            assert r2.status_code == 200
            assert r2.json()["messages_received"] == 5

            # Stage 1 → Stage 2 → Stage 3 → Stage 4 → FACILITATE
            assert len(received) == 1, "Expected outbound facilitation call after alarming payload"
            batch = received[0]["facilitation_responses"]
            assert len(batch) == 1
            assert batch[0]["group_id"] == GROUP_ID
            assert batch[0]["question_id"] == QUESTION_ID
            assert batch[0]["content"] == safety_message

            # Both payloads accumulated: 10 messages total
            logs2 = await e2e_client.get(
                f"/api/v1/messages/logs?group_id={GROUP_ID}", headers=headers
            )
            assert logs2.status_code == 200
            assert len(logs2.json()) == 10
