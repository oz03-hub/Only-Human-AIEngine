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
| FR-7 | Return facilitation messages to chat application | High | Implemented |
| FR-8 | Scheduled batch processing for chatrooms (every 10 min) | Medium | Implemented |
| FR-9 | Health check endpoint for monitoring | Medium | Implemented |
| FR-10 | API key authentication for all endpoints | High | Implemented |

### 1.3 Data Management

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-11 | Store conversation messages per chatroom | High | Implemented |
| FR-12 | Log all facilitation decisions and outcomes | High | Implemented |
| FR-13 | Track chatroom metadata (participants, last activity) | Medium | Implemented |
| FR-14 | Retrieve conversation history for pipeline processing | High | Implemented |

---

## 2. Tech Stack

### 2.1 Backend Framework

| Component | Technology | Justification |
|-----------|------------|---------------|
| Web Framework | **FastAPI** | Async support, automatic OpenAPI docs, Pydantic validation |
| ASGI Server | **Uvicorn** | High-performance async server for FastAPI |

### 2.2 Machine Learning

| Component | Technology | Justification |
|-----------|------------|---------------|
| ML Framework | **scikit-learn** | Pre-trained Random Forest model already uses joblib/sklearn |

### 2.3 LLM Integration

| Component | Technology | Justification |
|-----------|------------|---------------|
| LLM Provider | **OpenAI API** | GPT-4o-mini for cost-effective inference |
| Python SDK | **openai** | Official Python client |
| Prompt Management | In-code templates | Simple for MVP, can migrate to LangChain later |

### 2.4 Database

| Component | Technology | Justification |
|-----------|------------|---------------|
| Development DB | **SQLite** | Single-file, zero-config, perfect for local dev |
| Production DB | **PostgreSQL** (Cloud SQL) | Robust, managed, scales well |
| ORM | **SQLAlchemy** | Industry standard, works with SQLite and PostgreSQL |
| Migrations | **Alembic** | Schema versioning and migrations |

### 2.5 Infrastructure (Production)

| Component | Technology | Justification |
|-----------|------------|---------------|
| Container Runtime | **Docker** | Consistent deployment, GCP compatible |
| Cloud Platform | **Google Cloud Platform** | Project requirement |
| Container Service | **Cloud Run** | Serverless containers, auto-scaling, cost-effective |
| Database Service | **Cloud SQL (PostgreSQL)** | Managed DB, automatic backups |
| Secrets Management | **Secret Manager** | Secure API key storage |

---

## 3. Development Phases

### Phase 1: Project Setup & Database
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
- [x] Implement conversation history retrieval
- [x] Add facilitation logs query endpoint

### Phase 3: Testing & Documentation
- [x] Write unit tests for services
- [x] Write integration tests for API endpoints
- [x] Test with sample conversation data

### Phase 5: Production Deployment
- [ ] Create production Dockerfile
- [ ] Set up Cloud SQL PostgreSQL instance
- [ ] Configure Cloud Run service
- [ ] Set up Secret Manager for API keys
- [ ] Deploy and test in staging environment
- [ ] Production deployment
