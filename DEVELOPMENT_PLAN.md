# AIEngine Development Plan

## Project Overview

**Project Name:** UMass AIEngine
**Purpose:** Multi-stage chat facilitation AI system for the "Only-Human" chat application
**Target Users:** Alzheimer's caregiver support groups on the FATHM platform
**Version:** MVP 1.0

---

## 1. Functional Requirements

### 1.1 Core Facilitation Pipeline

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1 | Execute 3-stage facilitation decision pipeline | High | Implemented |
| FR-2 | Stage 1: Random Forest temporal classification | High | Implemented |
| FR-3 | Stage 2: LLM zero-shot verification | High | Implemented |
| FR-4 | Stage 3: LLM facilitation message generation | High | Implemented |
| FR-5 | Early termination at each stage if facilitation not needed | High | Implemented |

### 1.2 API Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-6 | Receive incoming messages via webhook endpoint | High | Not Started |
| FR-7 | Return facilitation messages to chat application | High | Not Started |
| FR-8 | Scheduled batch processing for chatrooms (every 30 min) | Medium | Not Started |
| FR-9 | Health check endpoint for monitoring | Medium | Not Started |
| FR-10 | API key authentication for all endpoints | High | Not Started |

### 1.3 Data Management

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-11 | Store conversation messages per chatroom | High | Not Started |
| FR-12 | Log all facilitation decisions and outcomes | High | Not Started |
| FR-13 | Track chatroom metadata (participants, last activity) | Medium | Not Started |
| FR-14 | Retrieve conversation history for pipeline processing | High | Not Started |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-1 | API response time | < 5 seconds (including LLM calls) |
| NFR-2 | System availability | 99% uptime |
| NFR-3 | Concurrent chatrooms supported | 50 (MVP) |
| NFR-4 | Data retention | 90 days minimum |
| NFR-5 | LLM API fallback handling | Graceful degradation on failures |

---

## 3. Tech Stack

### 3.1 Backend Framework

| Component | Technology | Justification |
|-----------|------------|---------------|
| Web Framework | **FastAPI** | Async support, automatic OpenAPI docs, Pydantic validation |
| ASGI Server | **Uvicorn** | High-performance async server for FastAPI |
| Task Scheduler | **APScheduler** | Lightweight scheduler for 30-min batch jobs |

### 3.2 Machine Learning

| Component | Technology | Justification |
|-----------|------------|---------------|
| ML Framework | **scikit-learn** | Pre-trained Random Forest model already uses joblib/sklearn |
| Model Serialization | **joblib** | Efficient model persistence, already in use |
| Numerical Computing | **NumPy** | Feature vector operations |

### 3.3 LLM Integration

| Component | Technology | Justification |
|-----------|------------|---------------|
| LLM Provider | **OpenAI API** | GPT-4o-mini for cost-effective inference |
| Python SDK | **openai** | Official Python client |
| Prompt Management | In-code templates | Simple for MVP, can migrate to LangChain later |

### 3.4 Database

| Component | Technology | Justification |
|-----------|------------|---------------|
| Development DB | **SQLite** | Single-file, zero-config, perfect for local dev |
| Production DB | **PostgreSQL** (Cloud SQL) | Robust, managed, scales well |
| ORM | **SQLAlchemy** | Industry standard, works with SQLite and PostgreSQL |
| Migrations | **Alembic** | Schema versioning and migrations |

### 3.5 Infrastructure (Production)

| Component | Technology | Justification |
|-----------|------------|---------------|
| Container Runtime | **Docker** | Consistent deployment, GCP compatible |
| Cloud Platform | **Google Cloud Platform** | Project requirement |
| Container Service | **Cloud Run** | Serverless containers, auto-scaling, cost-effective |
| Database Service | **Cloud SQL (PostgreSQL)** | Managed DB, automatic backups |
| Secrets Management | **Secret Manager** | Secure API key storage |

---

## 4. Database Design

### 4.1 Schema Overview

```
┌─────────────────┐     ┌─────────────────────┐
│   chatrooms     │     │     messages        │
├─────────────────┤     ├─────────────────────┤
│ id (PK)         │────<│ id (PK)             │
│ external_id     │     │ chatroom_id (FK)    │
│ name            │     │ sender_id           │
│ created_at      │     │ sender_name         │
│ last_activity   │     │ content             │
│ is_active       │     │ timestamp           │
└─────────────────┘     │ created_at          │
                        └─────────────────────┘
                                  │
                                  │
┌─────────────────────────────────┴───────────────┐
│              facilitation_logs                  │
├─────────────────────────────────────────────────┤
│ id (PK)                                         │
│ chatroom_id (FK)                                │
│ triggered_at                                    │
│ stage1_result (JSON)                            │
│ stage2_result (JSON)                            │
│ stage3_result (JSON)                            │
│ final_decision (ENUM: NO_FACILITATION,          │
│                 NO_FACILITATION_AFTER_VERIFY,   │
│                 FACILITATE)                     │
│ facilitation_message                            │
│ message_sent_at                                 │
└─────────────────────────────────────────────────┘
```

### 4.2 SQLite for Development

For local development, we'll use SQLite stored in a single file:

```
data/
└── aiengine.db          # SQLite database file (gitignored)
```

**Advantages of SQLite for development:**
- Zero configuration required
- No separate database server to run
- Database is a single portable file
- Full SQL support
- Easy to reset (just delete the file)
- SQLAlchemy abstracts differences from PostgreSQL

---

## 5. Database Hosting Trade-offs (Production)

### Option A: Google Cloud SQL (Managed PostgreSQL)

| Pros | Cons |
|------|------|
| Fully managed (backups, patching, scaling) | Higher cost (~$10-50/month for smallest instance) |
| High availability options | Slight vendor lock-in |
| Automatic failover | Requires VPC configuration |
| Built-in monitoring and logging | |
| Easy integration with Cloud Run | |

**Estimated Cost:** ~$15-25/month for db-f1-micro instance

### Option B: Self-Hosted (VM with PostgreSQL)

| Pros | Cons |
|------|------|
| Lower cost for small workloads | Manual backup management |
| Full control over configuration | Manual security patching |
| No vendor lock-in | You manage availability/failover |
| Can use same VM for other services | Requires DevOps expertise |

**Estimated Cost:** ~$5-10/month for e2-micro VM

### Option C: Cloud Run + SQLite (Persistent Volume)

| Pros | Cons |
|------|------|
| Simplest setup | Not suitable for production scale |
| Lowest cost | No concurrent write support |
| Good for very small deployments | Data loss risk if misconfigured |

**Estimated Cost:** ~$1-5/month

### Recommendation

For your scale (< 50 chatrooms) and MVP phase:

1. **Development:** SQLite (local file)
2. **Staging/Production:** **Cloud SQL PostgreSQL (Option A)**

**Rationale:** Cloud SQL is simpler because:
- No server management overhead
- Automatic backups protect against data loss
- Easy to scale if usage grows
- Cloud Run connects seamlessly via Cloud SQL connector
- Time saved on DevOps justifies small cost difference

---

## 6. API Design

### 6.1 Endpoints

```
POST /api/v1/messages/webhook
    - Receive new messages from chat application
    - Triggers facilitation check if conditions met
    - Auth: API Key

POST /api/v1/facilitation/check
    - Manually trigger facilitation check for a chatroom
    - Auth: API Key

GET /api/v1/chatrooms/{chatroom_id}/history
    - Get conversation history
    - Auth: API Key

GET /api/v1/facilitation/logs
    - Get facilitation decision logs
    - Query params: chatroom_id, start_date, end_date
    - Auth: API Key

GET /health
    - Health check endpoint
    - No auth required
```

### 6.2 Webhook Payload (Incoming)

```json
{
  "group_id": "chatroom-uuid",
  "user_id": "user-uuid",
  "content": "Hello everyone",
  "timestamp": "2024-01-15T14:30:00Z",
}
```

### 6.3 Facilitation Response (Outgoing)

```json
{
  "group_id": "chatroom-uuid",
  "message": "It sounds like everyone is going through...",
}
```

---

## 7. Project Structure

```
AIEngine/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application entry
│   ├── config.py               # Configuration management
│   ├── dependencies.py         # Dependency injection
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── messages.py     # Webhook endpoint
│   │   │   ├── facilitation.py # Facilitation endpoints
│   │   │   └── health.py       # Health check
│   │   └── middleware/
│   │       ├── __init__.py
│   │       └── auth.py         # API key authentication
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── pipeline.py         # FacilitationDecisionPipeline (refactored)
│   │   ├── feature_extractor.py
│   │   └── scheduler.py        # APScheduler for batch jobs
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py         # SQLAlchemy models
│   │   └── schemas.py          # Pydantic schemas
│   │
│   └── services/
│       ├── __init__.py
│       ├── message_service.py  # Message CRUD operations
│       ├── facilitation_service.py
│       └── llm_service.py      # OpenAI API wrapper
│
├── models/                     # ML models (existing)
│   └── rf_classifier.pkl
│
├── data/                       # Local database (gitignored)
│   └── aiengine.db
│
├── migrations/                 # Alembic migrations
│   └── versions/
│
├── tests/
│   ├── __init__.py
│   ├── test_api/
│   ├── test_core/
│   └── test_services/
│
├── Dockerfile
├── docker-compose.yml          # Local dev with services
├── requirements.txt
├── .env.example
├── alembic.ini
├── README.md
├── CLAUDE.md
└── DEVELOPMENT_PLAN.md         # This file
```

---

## 8. Dependencies

### 8.1 requirements.txt

```
# Web Framework
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
python-multipart>=0.0.6

# Database
sqlalchemy>=2.0.0
alembic>=1.13.0
aiosqlite>=0.19.0          # Async SQLite for development
asyncpg>=0.29.0            # Async PostgreSQL for production

# ML & Data
scikit-learn>=1.4.0
joblib>=1.3.0
numpy>=1.26.0

# LLM
openai>=1.10.0

# Utilities
python-dotenv>=1.0.0
pydantic>=2.5.0
pydantic-settings>=2.1.0

# Scheduling
apscheduler>=3.10.0

# Testing
pytest>=8.0.0
pytest-asyncio>=0.23.0
httpx>=0.26.0              # Async test client

# Production
gunicorn>=21.0.0           # Production WSGI server
```

---

## 9. Development Phases

### Phase 1: Project Setup & Database ✓
- [x] Initialize FastAPI project structure
- [x] Set up SQLAlchemy with SQLite
- [x] Create database models (chatrooms, messages, facilitation_logs)
- [x] Set up Alembic migrations
- [x] Create basic health check endpoint
- [x] Docker setup for local development

### Phase 2: Core API & Integration
- [ ] Implement webhook endpoint for receiving messages
- [ ] Refactor existing pipeline code into service layer
- [ ] Implement message storage service
- [ ] Implement facilitation logging service
- [ ] Add API key authentication middleware

### Phase 3: Scheduling & Background Jobs
- [ ] Implement APScheduler for 30-minute batch checks
- [ ] Add manual facilitation trigger endpoint
- [ ] Implement conversation history retrieval
- [ ] Add facilitation logs query endpoint

### Phase 4: Testing & Documentation
- [ ] Write unit tests for services
- [ ] Write integration tests for API endpoints
- [ ] Test with sample conversation data
- [ ] Generate OpenAPI documentation
- [ ] Update README with API usage examples

### Phase 5: Production Deployment
- [ ] Create production Dockerfile
- [ ] Set up Cloud SQL PostgreSQL instance
- [ ] Configure Cloud Run service
- [ ] Set up Secret Manager for API keys
- [ ] Deploy and test in staging environment
- [ ] Production deployment

---

## 10. Environment Variables

```bash
# .env.example

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/aiengine.db  # Dev
# DATABASE_URL=postgresql+asyncpg://user:pass@host/db  # Prod

# OpenAI
OPENAI_API_KEY=sk-...

# API Security
API_KEY=your-secure-api-key-here

# Application
ENV=development  # development | staging | production
LOG_LEVEL=INFO
MODEL_PATH=models/rf_classifier.pkl
LLM_MODEL=gpt-4o-mini

# Scheduler
FACILITATION_CHECK_INTERVAL_MINUTES=30
```

---

## 11. Monitoring & Logging

### 11.1 GCP Native Monitoring (Recommended)

Cloud Run provides built-in observability with minimal setup:

| Service | What It Does | Setup Required |
|---------|--------------|----------------|
| **Cloud Logging** | Captures stdout/stderr from containers | Automatic |
| **Cloud Monitoring** | CPU, memory, request count, latency metrics | Automatic |
| **Error Reporting** | Groups and tracks exceptions | Automatic (Python exceptions) |
| **Cloud Trace** | Distributed tracing for request latency | Add `opentelemetry` library |

### 11.2 Application-Level Logging

Add structured logging to FastAPI for better log queries:

```python
# In app/config.py
import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "timestamp": self.formatTime(record)
        }
        return json.dumps(log_obj)
```

**Key events to log:**
- Webhook received (chatroom_id, message count)
- Pipeline stage results (decision, confidence)
- Facilitation sent (chatroom_id, approach)
- LLM API errors (retry count, error type)

### 11.3 Alerts (Optional but Recommended)

Set up in Cloud Monitoring console:

| Alert | Condition | Action |
|-------|-----------|--------|
| High error rate | >5% of requests return 5xx | Email notification |
| LLM API failures | >3 consecutive failures | Email notification |
| High latency | P95 > 10 seconds | Email notification |

### 11.4 Dependencies for Monitoring

```
# Add to requirements.txt (optional, for enhanced tracing)
opentelemetry-instrumentation-fastapi>=0.43b0
opentelemetry-exporter-gcp-trace>=1.6.0
```

**Bottom line:** Cloud Run + Cloud Logging gives you 80% of what you need with zero setup. Structured JSON logging in your app makes searching logs easier. Alerts are optional but cheap insurance.

---

## 12. Open Questions / Future Considerations

1. **Rate Limiting:** Should we implement rate limiting on the webhook endpoint?
2. **Retry Logic:** How should we handle OpenAI API failures? Retry or skip?
3. **Message Deduplication:** How do we handle duplicate messages from the chat app?
4. **Feedback Loop:** Will there be a way to capture if facilitation was helpful?
5. **Model Retraining:** Process for updating the Random Forest model?
6. **Multi-tenancy:** Will this serve multiple FATHM instances or just one?

---

## 13. Appendix: Database Comparison Summary

| Aspect | SQLite (Dev) | Cloud SQL (Prod) | Self-Hosted |
|--------|--------------|------------------|-------------|
| Setup Time | 5 min | 30 min | 2-4 hours |
| Monthly Cost | $0 | ~$15-25 | ~$5-10 |
| Maintenance | None | Minimal | Significant |
| Scalability | Single user | High | Medium |
| Backups | Manual | Automatic | Manual |
| Best For | Development | Production | Cost-sensitive |

**Final Recommendation:** SQLite for development, Cloud SQL for production.

---

*Document Version: 1.0*
*Last Updated: 2025-01-10*
*Author: Development Team*
