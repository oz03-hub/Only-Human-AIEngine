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

### API Endpoints

#### Health Check
```bash
GET /health
# No authentication required
```

#### Webhook for Messages
```bash
POST /api/v1/messages/webhook
# Requires X-API-Key header
# Receives and stores batch messages
# Returns 200 OK with summary (no facilitation processing)
```

#### Manual Facilitation Check
```bash
POST /api/v1/facilitation/check
# Requires X-API-Key header
# Manually trigger facilitation check for a chatroom
```

#### Get Facilitation Logs
```bash
GET /api/v1/facilitation/logs?group_id=<chatroom-uuid>&limit=10
# Requires X-API-Key header
# Retrieve facilitation decision logs
```

### Example API Requests

#### Send messages to webhook
```bash
curl -X POST http://localhost:8000/api/v1/messages/webhook \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key-here" \
  -d '{
    "messages": [
      {
        "group_id": "chatroom-uuid-123",
        "user_id": "user-uuid-456",
        "user_name": "Alice",
        "content": "Hello everyone",
        "timestamp": "2024-01-15T14:30:00Z"
      }
    ]
  }'
```

Response:
```json
{
  "status": "success",
  "messages_received": 1,
  "chatrooms_affected": 1
}
```

#### Manually trigger facilitation check
```bash
curl -X POST http://localhost:8000/api/v1/facilitation/check \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key-here" \
  -d '{
    "group_id": "chatroom-uuid-123"
  }'
```

Response:
```json
{
  "group_id": "chatroom-uuid-123",
  "decision": "FACILITATE",
  "message": "It sounds like everyone is going through similar challenges...",
  "log_id": 42
}
```

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


## MVP Notes
1. We can run the workflow every 30 minutes on each active chatroom to determine if it needs facilitation.
2. For database, we will probably need a relational database, unless there is a no-sql version that we can develop with easily.
3. Example projected API schemas.
```
// Forward new messages to UMass AI
async function onNewMessage(groupId, message) {
  await umasAIClient.send({
    groupId: groupId,
    userId: message.userId,
    content: message.content,
    timestamp: message.createdAt,
    context: await getGroupConversationHistory(groupId)
  });
}

// Receive and display AI responses
async function onAIResponse(groupId, aiResponse) {
  await db.insert(chatMessages).values({
    channelId: groupId,
    userId: AI_PARTICIPANT.id,
    userName: AI_PARTICIPANT.name,
    content: aiResponse.message,
    isAI: true
  });
}
```
The chat app will use these functions to send the AIEngine data.

4. Right now, we don't have all the details about schemas, APIs from the chat application, so for now, let's focus on laying out the core API.
5. A simple version of the entire pipeline can be found at 
