# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UMass AIEngine is a multi-stage chat facilitation AI system. It determines when and how to inject facilitation messages into group conversations.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Alembic, OpenAI API, scikit-learn

## Quick Start

```bash
# Activate virtual environment
source .venv/bin/activate

# Run database migrations
alembic upgrade head

# Start development server
python -m app.main
# Server runs at http://localhost:8000
# API docs at http://localhost:8000/docs
```

## Application Structure

```
app/
├── main.py              # FastAPI application entry point
├── config.py            # Environment configuration (Pydantic Settings)
├── dependencies.py      # Dependency injection (database sessions)
│
├── api/
│   ├── routes/
│   │   ├── health.py        # Health check endpoint
│   │   ├── messages.py      # Webhook for incoming messages (Phase 2)
│   │   └── facilitation.py  # Facilitation endpoints (Phase 2)
│   └── middleware/
│       └── auth.py          # API key authentication (Phase 2)
│
├── core/
│   ├── pipeline.py          # FacilitationDecisionPipeline (Phase 2)
│   ├── feature_extractor.py # TemporalFeatureExtractor (Phase 2)
│
├── models/
│   ├── database.py      # SQLAlchemy models (Chatroom, Message, FacilitationLog)
│   └── schemas.py       # Pydantic schemas for API validation
│
└── services/
    ├── message_service.py      # Message CRUD operations (Phase 2)
    ├── facilitation_service.py # Pipeline orchestration (Phase 2)
    └── llm_service.py          # OpenAI API wrapper (Phase 2)
```

## Tech Stack Explained

### **SQLAlchemy** (Database ORM)
- Converts Python classes ↔ database tables
- Type-safe database operations without writing SQL

### **Pydantic** (Data Validation)
- Validates incoming/outgoing API data automatically
- FastAPI uses it to ensure correct data types before reaching your code

### **Alembic** (Database Migrations)
- Version control for database schema changes
- Safely update database structure without losing data
- Generate migration: `alembic revision --autogenerate -m "description"`
- Apply migration: `alembic upgrade head`

## Facilitation Pipeline Architecture

The system implements a 3-stage decision pipeline with early termination:

```
Stage 1: Temporal Classification (Random Forest)
    ↓ (if facilitation indicated)
Stage 2: LLM Zero-Shot Verification (gpt-4o-mini)
    ↓ (if verified)
Stage 3: Generate Facilitation Message
```

**Stage 1:** Pre-trained Random Forest classifier analyzes temporal features (message counts in windows, gaps between messages)

**Stage 2:** LLM verifies facilitation need based on conversation content (staleness, conflict, distress, dominance, low engagement)

**Stage 3:** LLM generates empathetic facilitation message (open-ended questions, emotional validation, gentle redirection)

## Database Schema

- **chatrooms** - Group conversation metadata
- **messages** - Individual chat messages with sender and timestamp
- **facilitation_logs** - Pipeline execution results (stage decisions, generated messages)

Database file: `data/aiengine.db` (SQLite for development)

## Development Workflow

1. **Make code changes** in `app/`
2. **Update database models?** Run `alembic revision --autogenerate -m "description"`
3. **Apply migrations:** `alembic upgrade head`
4. **Test endpoints:** Use http://localhost:8000/docs (Swagger UI)
5. **Check logs:** Server outputs structured logs to stdout

## Reference Files

- `facilitate.py` and `feature_extractor.py` - Pilot implementation for reference when building Phase 2
- `models/temporal_classifier.pkl` - Pre-trained Random Forest model
- `.env` - Environment variables (OPENAI_API_KEY, DATABASE_URL, etc.)

## Example Server Workflow

1. Server recieves `messages/webhook/`.
2. Stores the messages in the payload to the database.
3. Replies with success to the application after storing.
4. After storing it starts the facilitation pipeline for the active groups present in the webhook payload.
5. If it triggers a facilitation for a group constructs a facilitation response and sends it to the application api.

## Development Notes

- LLM stages use structured JSON responses with fallback handling
- API key authentication required for all endpoints except `/health`
- CORS configured for development (all origins) and production (Only-Human domains)
