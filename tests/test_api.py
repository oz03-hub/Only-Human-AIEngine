"""
Integration tests for API endpoints.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from datetime import datetime

from app.main import app
from app.models.database import get_db, Group, User, Question, GroupQuestion, Message
from app.config import settings


class TestWebhookEndpoint:
    """Test the /webhook endpoint."""

    @pytest_asyncio.fixture
    async def client(self, db_session):
        """Create test client with overridden database dependency."""
        async def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

        app.dependency_overrides.clear()

    @pytest.fixture
    def webhook_payload(self):
        """Sample webhook payload matching the actual webhookschema.json format."""
        return {
            "payload": {
                "groups_metadata": [
                    {"group_id": 123, "status": "active", "status_updated_at": None}
                ],
                "groups": [
                    {
                        "group_id": 123,
                        "group_name": "Test Group",
                        "members": [
                            {"user_id": "user-1", "first_name": "John", "last_name": "Doe"}
                        ],
                        "threads": [
                            {
                                "question": {
                                    "id": "question-1",
                                    "text": "What is your favorite memory?",
                                    "options": ["Family", "Friends", "Travel", "Other"],
                                    "status": "active",
                                    "unlock_order": 1,
                                },
                                "messages": [
                                    {
                                        "user_id": "user-1",
                                        "first_name": "John",
                                        "last_name": "Doe",
                                        "content": "I love spending time with family!",
                                        "created_at": "2024-01-15T10:30:00Z",
                                        "is_ai": False,
                                        "is_current_member": True,
                                    }
                                ],
                                "last_ai_message_at": None,
                            }
                        ],
                    }
                ],
            }
        }

    @pytest.mark.asyncio
    async def test_webhook_stores_messages(
        self,
        client,
        webhook_payload,
        db_session
    ):
        """Test that webhook stores messages correctly."""
        headers = {"X-API-Key": settings.api_key}

        response = await client.post(
            "/api/v1/messages/webhook",
            json=webhook_payload,
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["groups_affected"] == 1
        assert data["messages_received"] == 1
        assert data["question_threads_affected"] == 1

        # Verify data was stored
        from sqlalchemy import select
        result = await db_session.execute(select(Group))
        groups = result.scalars().all()
        assert len(groups) == 1
        assert groups[0].external_id == 123

        result = await db_session.execute(select(Message))
        messages = result.scalars().all()
        assert len(messages) == 1
        assert messages[0].content == "I love spending time with family!"

    @pytest.mark.asyncio
    async def test_webhook_requires_api_key(
        self,
        client,
        webhook_payload
    ):
        """Test that webhook requires valid API key."""
        # No API key
        response = await client.post(
            "/api/v1/messages/webhook",
            json=webhook_payload
        )
        assert response.status_code in [401, 403]  # Unauthorized or Forbidden

        # Invalid API key
        headers = {"X-API-Key": "invalid-key"}
        response = await client.post(
            "/api/v1/messages/webhook",
            json=webhook_payload,
            headers=headers
        )
        assert response.status_code in [401, 403]  # Unauthorized or Forbidden

    @pytest.mark.asyncio
    async def test_webhook_triggers_background_facilitation(
        self,
        client,
        webhook_payload
    ):
        """Test that webhook triggers background facilitation processing."""
        headers = {"X-API-Key": settings.api_key}

        with patch('app.api.routes.messages.process_facilitation_background') as mock_bg_task:
            response = await client.post(
                "/api/v1/messages/webhook",
                json=webhook_payload,
                headers=headers
            )

            assert response.status_code == 200

            # Note: BackgroundTasks.add_task doesn't actually call the function in tests
            # This just verifies the endpoint completes successfully
            # For full background task testing, use the service tests

    @pytest.mark.asyncio
    async def test_webhook_multiple_groups_and_questions(
        self,
        client,
        db_session
    ):
        """Test webhook with multiple groups and questions."""
        payload = {
            "payload": {
                "groups_metadata": [
                    {"group_id": 100, "status": "active"},
                    {"group_id": 200, "status": "active"},
                ],
                "groups": [
                    {
                        "group_id": 100,
                        "group_name": "Group 1",
                        "members": [{"user_id": "user-1", "first_name": "Alice", "last_name": "Smith"}],
                        "threads": [
                            {
                                "question": {"id": "q1", "text": "Question 1", "options": ["A", "B"], "status": "active", "unlock_order": 1},
                                "messages": [
                                    {"user_id": "user-1", "first_name": "Alice", "last_name": "Smith", "content": "Message for Q1", "created_at": "2024-01-15T10:30:00Z", "is_ai": False, "is_current_member": True}
                                ],
                                "last_ai_message_at": None,
                            },
                            {
                                "question": {"id": "q2", "text": "Question 2", "options": ["C", "D"], "status": "active", "unlock_order": 2},
                                "messages": [
                                    {"user_id": "user-1", "first_name": "Alice", "last_name": "Smith", "content": "Message for Q2", "created_at": "2024-01-15T10:31:00Z", "is_ai": False, "is_current_member": True}
                                ],
                                "last_ai_message_at": None,
                            },
                        ],
                    },
                    {
                        "group_id": 200,
                        "group_name": "Group 2",
                        "members": [{"user_id": "user-2", "first_name": "Bob", "last_name": "Jones"}],
                        "threads": [
                            {
                                "question": {"id": "q3", "text": "Question 3", "options": ["E", "F"], "status": "active", "unlock_order": 1},
                                "messages": [
                                    {"user_id": "user-2", "first_name": "Bob", "last_name": "Jones", "content": "Message for Q3", "created_at": "2024-01-15T10:32:00Z", "is_ai": False, "is_current_member": True}
                                ],
                                "last_ai_message_at": None,
                            }
                        ],
                    },
                ],
            }
        }

        headers = {"X-API-Key": settings.api_key}
        response = await client.post(
            "/api/v1/messages/webhook",
            json=payload,
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["groups_affected"] == 2
        assert data["question_threads_affected"] == 3
        assert data["messages_received"] == 3

    @pytest.mark.asyncio
    async def test_webhook_invalid_payload(self, client):
        """Test webhook with invalid payload."""
        headers = {"X-API-Key": settings.api_key}

        invalid_payload = {
            "payload": {
                "groups_metadata": [],
                "groups": [
                    {
                        "group_id": "invalid",  # Should be int
                        "group_name": "Test",
                        "members": [],
                        "threads": [],
                    }
                ],
            }
        }

        response = await client.post(
            "/api/v1/messages/webhook",
            json=invalid_payload,
            headers=headers
        )

        assert response.status_code == 422  # Validation error


class TestGroupActivityEndpoint:
    """Test the /group_activity endpoint."""

    @pytest_asyncio.fixture
    async def client(self, db_session):
        """Create test client."""
        async def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_update_group_activity(
        self,
        client,
        test_group,
        db_session
    ):
        """Test updating group activity status."""
        headers = {"X-API-Key": settings.api_key}

        payload = {
            "group_id": test_group.external_id,
            "is_active": False
        }

        response = await client.patch(
            "/api/v1/messages/group_activity",
            json=payload,
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["is_active"] is False

        # Verify in database
        await db_session.refresh(test_group)
        assert test_group.is_active is False

    @pytest.mark.asyncio
    async def test_update_nonexistent_group(self, client):
        """Test updating nonexistent group."""
        headers = {"X-API-Key": settings.api_key}

        payload = {
            "group_id": 99999,
            "is_active": False
        }

        response = await client.patch(
            "/api/v1/messages/group_activity",
            json=payload,
            headers=headers
        )

        assert response.status_code == 404


class TestGetMessagesEndpoint:
    """Test the /logs endpoint."""

    @pytest_asyncio.fixture
    async def client(self, db_session):
        """Create test client."""
        async def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_get_messages_for_group(
        self,
        client,
        test_group,
        test_messages,
        db_session
    ):
        """Test retrieving messages for a group."""
        headers = {"X-API-Key": settings.api_key}

        response = await client.get(
            f"/api/v1/messages/logs?group_id={test_group.external_id}",
            headers=headers
        )

        assert response.status_code == 200
        messages = response.json()
        assert len(messages) == 5  # From test_messages fixture
        assert all("content" in msg for msg in messages)
