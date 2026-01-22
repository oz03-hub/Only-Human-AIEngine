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
| FR-6 | Receive incoming messages via webhook endpoint | High | Implemented |
| FR-7 | Return facilitation messages to chat application | High | Not Started |
| FR-8 | Scheduled batch processing for chatrooms (every 30 min) | Medium | Not Started |
| FR-9 | Health check endpoint for monitoring | Medium | Implemented |
| FR-10 | API key authentication for all endpoints | High | Implemented |

### 1.3 Data Management

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-11 | Store conversation messages per chatroom | High | Implemented |
| FR-12 | Log all facilitation decisions and outcomes | High | Not Started |
| FR-13 | Track chatroom metadata (participants, last activity) | Medium | Implemented |
| FR-14 | Retrieve conversation history for pipeline processing | High | Implemented |

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
│ id (PK)         │     │ id (PK)             │
│ external_id     │     │ chatroom_id (FK)    │
│ name            │     │ sender_id           │
│ created_at      │     │ sender_name         │
│                 │     │ content             │
│ is_active       │     │ timestamp           │
└─────────────────┘     │ created_at          │
                        └─────────────────────┘
                                  
┌─────────────────────────────────────────────────┐
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
## 5. Database Hosting Trade-offs (Production)

### Google Cloud SQL
| Pros | Cons |
|------|------|
| Fully managed (backups, patching, scaling) | Higher cost (~$10-50/month for smallest instance) |
| High availability options | Slight vendor lock-in |
| Automatic failover | Requires VPC configuration |
| Built-in monitoring and logging | |
| Easy integration with Cloud Run | |

**Estimated Cost:** ~$15-25/month for db-f1-micro instance

---

## 6. API Design

### 6.1 Endpoints

```
POST /api/v1/messages/webhook
    - Receive new batch of messages from chat application
    - Auth: API Key

GET /api/v1/messages/logs
    - Recieve history of messages for a chatroom
    - Auth: API Key

POST /api/v1/facilitation/check
    - Manually trigger facilitation check for a chatroom
    - Auth: API Key

GET /api/v1/facilitation/logs
    - Get facilitation decision logs
    - Query params: chatroom_id, start_date, end_date
    - Auth: API Key

GET /health
    - Health check endpoint
    - No auth required
```

---

## 7. Development Phases

### Phase 1: Project Setup & Database ✓
- [x] Initialize FastAPI project structure
- [x] Set up SQLAlchemy with SQLite
- [x] Create database models (chatrooms, messages, facilitation_logs)
- [x] Set up Alembic migrations
- [x] Create basic health check endpoint
- [x] Docker setup for local development

### Phase 2: Core API & Integration
- [x] Implement webhook endpoint for receiving messages
- [x] Refactor existing pipeline code into service layer
- [x] Implement message storage service
- [x] Implement facilitation logging service
- [x] Add API key authentication middleware

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
## 8. Monitoring & Logging

### 8.1 GCP Native Monitoring

Cloud Run provides built-in observability with minimal setup:

| Service | What It Does | Setup Required |
|---------|--------------|----------------|
| **Cloud Logging** | Captures stdout/stderr from containers | Automatic |
| **Cloud Monitoring** | CPU, memory, request count, latency metrics | Automatic |
