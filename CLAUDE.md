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
│   ├── Unused currently
│
├── models/
│   ├── database.py      # SQLAlchemy models (Chatroom, Message, FacilitationLog)
│   └── schemas.py       # Pydantic schemas for API validation
│
└── services/
    ├── message_service.py      # Message CRUD operations (Phase 2)
    ├── webhook_service.py
    ├── facilitator # facilitation logic that needs to be updated to fit the server
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

The system implements a 4-stage decision pipeline with early termination. All logic exists in `app/services/facilitator/`:

```
Stage 1: Temporal Classification (Random Forest)
    ↓ (if facilitation indicated)
Stage 2: LLM Zero-Shot Verification
    ↓ (if verified)
Stage 3: Generate Facilitation Message
    ↓
Stage 4: Check for Red-flags, return stage 3 if any, if not sends the message
```

## Incoming Request Example
The client application will send a request to this server every 20 minutes with new messages or changes in the client application.

The `webhookschema.json` has the format example of the incoming requests.

A few notes:
- Each request payload will contain all existing groups in the app, when a request comes in we need to handle creation in the database if a new group comes
- Each group has threads, and the threads are where the conversation happens.
- Each group, thread pair can be imagined as a unique text channel that needs facilitation.
- Each thread has the same members as the group, so there should also be a members table.
- We only need to check for facilitation in "active" threads. We should sync the status of all threads with what is provided in the payload.
- For facilitation, with each incoming requests we will check for facilitation for active threads in the payload, and will check all other threads that are also active but was not in the payload with 20% chance.

Database file: `data/aiengine.db` (SQLite for development)

## Development Workflow

1. **Make code changes** in `app/`
2. **Update database models?** Run `alembic revision --autogenerate -m "description"`
3. **Apply migrations:** `alembic upgrade head`
4. **Test endpoints:** Use http://localhost:8000/docs (Swagger UI)
5. **Check logs:** Server outputs structured logs to stdout

## Reference Files
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
