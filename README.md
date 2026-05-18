This is the UMass AIEngine for the Only-Human chat application.

It serves the logic for the AI facilitation BOT.

## Quick Start

### Prerequisites
- Python 3.12
- OpenAI API key
- API key for webhook authentication

### Installation

0. **Create an API key:**
```bash
openssl rand -hex 32
```
Note it down and save to `.env` in step 3.

1. **Create a virtual environment:**
```bash
python -m venv .venv
```

2. **Activate virtual environment:**
```bash
source .venv/bin/activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Configure environment variables:**
```bash
# Copy example and edit with your keys
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY and API_KEY
```

4. **Create data directory and run database migrations:**
```bash
mkdir -p data
alembic upgrade head
```

### Running the Server

Start the development server:
```bash
python -m app.main
```

The server will start at `http://localhost:8000`

### API Documentation

Once the server is running, you can access the interactive API documentation:

- **Swagger UI (recommended):** http://localhost:8000/docs

The Swagger UI allows you to:
- View all available endpoints
- See request/response schemas
- Test endpoints directly in the browser
- Try out API calls with your API key

## Workflow for facilitation
1. As the first stage, we will run the Random Forest model to determine if facilitation is needed based on temporal features.
    1. To extract temporal features, we will use feature_extractor.py
    2. Model is saved in `models/temporal_classifier.pkl`.
2. If the first stage determines the chat needs facilitation, we will move on to the second stage.
3. As the second stage, we will make an API request to OpenAI to provide the recent conversation to ask it again if it needs facilitation.
4. If the second stage replies it needs facilitation, we will move on to the third stage.
5. As the third stage, we will use the recent messages in the chat to craft the facilitation message.
6. The third stage message is checked by a fourth stage for red-flags, if not approved, it is recycled to craft a new one, if passed, it is sent to client.

## File Tree

```
Only-Human-AIEngine/
├── app/                            # Main application package
│   ├── main.py                     # FastAPI app entry point, startup/shutdown
│   ├── config.py                   # Pydantic Settings env config
│   ├── dependencies.py             # DB session dependency injection
│   ├── api/
│   │   ├── middleware/
│   │   │   └── auth.py             # API key authentication middleware
│   │   └── routes/
│   │       ├── health.py           # GET /health endpoint
│   │       ├── messages.py         # POST /messages/webhook — receives payloads
│   │       └── facilitation.py     # Facilitation-related endpoints
│   ├── models/
│   │   ├── database.py             # SQLAlchemy ORM models (Chatroom, Message, etc.)
│   │   └── schemas.py              # Pydantic schemas for request/response validation
│   └── services/
│       ├── message_service.py      # Message CRUD operations
│       ├── facilitation_service.py # Orchestrates facilitation checks per thread
│       ├── webhook_client.py       # HTTP client to send facilitation back to app
│       └── facilitator/            # 4-stage facilitation pipeline
│           ├── pipeline.py         # Runs stages 1–4 in sequence
│           ├── feature_extractor.py# Extracts temporal features for stage 1
│           ├── llm_service.py      # OpenAI API calls for stages 2, 3, 4
│           └── prompts.py          # All LLM prompt templates
│
├── migrations/                     # Alembic migration scripts
│   └── versions/                   # Versioned schema change files
│
├── models/                         # Trained ML model artifacts
│   └── temporal_classifier.pkl     # Pre-trained Random Forest (stage 1)
│
├── tests/                          # Test suite
│   ├── conftest.py                 # Shared fixtures
│   ├── test_api.py                 # API route tests
│   ├── test_pipeline.py            # Facilitation pipeline unit tests
│   ├── test_facilitation_service.py
│   ├── test_facilitation_e2e.py    # End-to-end facilitation flow tests
│   ├── test_webhook_client.py
│   ├── test_schemas.py
│   └── smoke_test.py               # Basic server health smoke test
│
├── data/                           # SQLite database (dev only, gitignored)
├── Dockerfile                      # Production container image
├── docker-compose.yml              # Local Docker Compose setup
├── alembic.ini                     # Alembic configuration
├── requirements.txt                # Python dependencies
└── .env.example                    # Environment variable template
```
