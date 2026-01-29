This is the UMass AIEngine for the Only-Human chat application.

It serves the logic for the AI facilitation BOT.

## Quick Start

### Prerequisites
- Python 3.10+
- Virtual environment activated
- OpenAI API key
- API key for webhook authentication

### Installation

1. **Activate virtual environment:**
```bash
source .venv/bin/activate
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Configure environment variables:**
```bash
# Copy example and edit with your keys
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY and API_KEY
```

4. **Run database migrations:**
```bash
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
- **ReDoc:** http://localhost:8000/redoc

The Swagger UI allows you to:
- View all available endpoints
- See request/response schemas
- Test endpoints directly in the browser
- Try out API calls with your API key

# Proposed Workflow
## Pre-requisites

1. The AI facilitator will be added to every chatroom as another participant.
2. The AIEngine will use provided chat API endpoints to read incoming new messages.
3. The AIEngine will use provided chat API endpoints to post a message.
4. The AIEngine will be given a pre-trained Random Forest Model to compute the first decision step.

## Workflow for facilitation
1. As the first stage, we will run the Random Forest model to determine if facilitation is needed based on temporal features.
    1. To extract temporal features, we will use feature_extractor.py
    2. Model is saved in `models/temporal_classifier.pkl`.
2. If the first stage determines the chat needs facilitation, we will move on to the second stage.
3. As the second stage, we will make an API request to OpenAI to provide the recent conversation to ask it again if it needs facilitation.
4. If the second stage replies it needs facilitation, we will move on to the third stage.
5. As the third stage, we will use the recent messages in the chat to craft the facilitation message.
