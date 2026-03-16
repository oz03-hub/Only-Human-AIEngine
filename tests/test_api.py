"""
Integration tests for API endpoints.
Focus: verify that the webhook actually stores the correct entities in the database.
"""

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from app.models.database import get_db, Group, Message, User, Member, Question, GroupQuestion
from app.config import settings


# ---------------------------------------------------------------------------
# Common payload helpers
# ---------------------------------------------------------------------------

def _make_payload(
    *,
    group_id: int = 123,
    group_name: str = "Test Group",
    group_status: str = "active",
    question_id: str = "question-1",
    question_text: str = "What is your favorite memory?",
    question_status: str = "active",
    user_id: str = "user-1",
    first_name: str = "John",
    last_name: str = "Doe",
    message_content: str = "I love spending time with family!",
):
    return {
        "payload": {
            "groups_metadata": [
                {"group_id": group_id, "status": group_status, "status_updated_at": None}
            ],
            "groups": [
                {
                    "group_id": group_id,
                    "group_name": group_name,
                    "members": [
                        {"user_id": user_id, "first_name": first_name, "last_name": last_name}
                    ],
                    "threads": [
                        {
                            "question": {
                                "id": question_id,
                                "text": question_text,
                                "options": ["Option A", "Option B"],
                                "status": question_status,
                                "unlock_order": 1,
                            },
                            "messages": [
                                {
                                    "user_id": user_id,
                                    "first_name": first_name,
                                    "last_name": last_name,
                                    "content": message_content,
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def headers():
    return {"X-API-Key": settings.api_key}


# ---------------------------------------------------------------------------
# /api/v1/messages/webhook  — storage correctness
# ---------------------------------------------------------------------------


class TestWebhookStorageCorrectness:
    """Verify that the webhook stores all entities correctly."""

    @pytest.mark.asyncio
    async def test_webhook_creates_group(self, client, headers, db_session):
        payload = _make_payload(group_id=501, group_name="My Group")
        await client.post("/api/v1/messages/webhook", json=payload, headers=headers)

        result = await db_session.execute(select(Group).where(Group.external_id == 501))
        group = result.scalar_one_or_none()
        assert group is not None
        assert group.group_name == "My Group"
        assert group.is_active is True

    @pytest.mark.asyncio
    async def test_webhook_creates_user(self, client, headers, db_session):
        payload = _make_payload(user_id="uid-42", first_name="Alice", last_name="Smith")
        await client.post("/api/v1/messages/webhook", json=payload, headers=headers)

        result = await db_session.execute(
            select(User).where(User.external_user_id == "uid-42")
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.first_name == "Alice"
        assert user.last_name == "Smith"

    @pytest.mark.asyncio
    async def test_webhook_creates_member_link(self, client, headers, db_session):
        """User is linked to group via the Member table."""
        payload = _make_payload(group_id=502, user_id="uid-member-test")
        await client.post("/api/v1/messages/webhook", json=payload, headers=headers)

        group_result = await db_session.execute(
            select(Group).where(Group.external_id == 502)
        )
        group = group_result.scalar_one()

        user_result = await db_session.execute(
            select(User).where(User.external_user_id == "uid-member-test")
        )
        user = user_result.scalar_one()

        member_result = await db_session.execute(
            select(Member).where(
                Member.group_id == group.id, Member.user_id == user.id
            )
        )
        member = member_result.scalar_one_or_none()
        assert member is not None

    @pytest.mark.asyncio
    async def test_webhook_creates_question(self, client, headers, db_session):
        payload = _make_payload(
            question_id="q-unique-99",
            question_text="What motivates you most?",
        )
        await client.post("/api/v1/messages/webhook", json=payload, headers=headers)

        result = await db_session.execute(
            select(Question).where(Question.external_id == "q-unique-99")
        )
        question = result.scalar_one_or_none()
        assert question is not None
        assert question.text == "What motivates you most?"

    @pytest.mark.asyncio
    async def test_webhook_creates_group_question_thread(self, client, headers, db_session):
        payload = _make_payload(
            group_id=503, question_id="q-thread-test", question_status="active"
        )
        await client.post("/api/v1/messages/webhook", json=payload, headers=headers)

        group_result = await db_session.execute(
            select(Group).where(Group.external_id == 503)
        )
        group = group_result.scalar_one()

        question_result = await db_session.execute(
            select(Question).where(Question.external_id == "q-thread-test")
        )
        question = question_result.scalar_one()

        gq_result = await db_session.execute(
            select(GroupQuestion).where(
                GroupQuestion.group_id == group.id,
                GroupQuestion.question_id == question.id,
            )
        )
        gq = gq_result.scalar_one_or_none()
        assert gq is not None
        assert gq.status == "active"

    @pytest.mark.asyncio
    async def test_webhook_stores_message_content(self, client, headers, db_session):
        payload = _make_payload(
            group_id=504, message_content="Hello world test message"
        )
        await client.post("/api/v1/messages/webhook", json=payload, headers=headers)

        result = await db_session.execute(select(Message))
        messages = result.scalars().all()
        assert len(messages) == 1
        assert messages[0].content == "Hello world test message"
        assert messages[0].is_ai is False

    @pytest.mark.asyncio
    async def test_webhook_idempotent_group_creation(self, client, headers, db_session):
        """Sending the same group twice doesn't create duplicate groups."""
        payload = _make_payload(group_id=505)
        await client.post("/api/v1/messages/webhook", json=payload, headers=headers)
        await client.post("/api/v1/messages/webhook", json=payload, headers=headers)

        result = await db_session.execute(
            select(Group).where(Group.external_id == 505)
        )
        groups = result.scalars().all()
        assert len(groups) == 1

    @pytest.mark.asyncio
    async def test_webhook_syncs_group_status_from_metadata(self, client, headers, db_session):
        """groups_metadata status=inactive marks the group as is_active=False."""
        payload = _make_payload(group_id=506, group_status="inactive")
        await client.post("/api/v1/messages/webhook", json=payload, headers=headers)

        result = await db_session.execute(
            select(Group).where(Group.external_id == 506)
        )
        group = result.scalar_one_or_none()
        # Group is created by the groups section, then status synced from metadata
        # inactive → is_active = False
        assert group is not None
        assert group.is_active is False

    @pytest.mark.asyncio
    async def test_webhook_multiple_groups(self, client, headers, db_session):
        """Multiple groups in one payload are all created."""
        payload = {
            "payload": {
                "groups_metadata": [
                    {"group_id": 601, "status": "active"},
                    {"group_id": 602, "status": "active"},
                ],
                "groups": [
                    {
                        "group_id": 601,
                        "group_name": "Group Alpha",
                        "members": [
                            {"user_id": "u-alpha", "first_name": "Alpha", "last_name": "A"}
                        ],
                        "threads": [
                            {
                                "question": {
                                    "id": "q-alpha",
                                    "text": "Alpha question",
                                    "options": [],
                                    "status": "active",
                                    "unlock_order": 1,
                                },
                                "messages": [
                                    {
                                        "user_id": "u-alpha",
                                        "first_name": "Alpha",
                                        "last_name": "A",
                                        "content": "Alpha message",
                                        "created_at": "2024-01-15T10:00:00Z",
                                        "is_ai": False,
                                        "is_current_member": True,
                                    }
                                ],
                                "last_ai_message_at": None,
                            }
                        ],
                    },
                    {
                        "group_id": 602,
                        "group_name": "Group Beta",
                        "members": [
                            {"user_id": "u-beta", "first_name": "Beta", "last_name": "B"}
                        ],
                        "threads": [
                            {
                                "question": {
                                    "id": "q-beta",
                                    "text": "Beta question",
                                    "options": [],
                                    "status": "active",
                                    "unlock_order": 1,
                                },
                                "messages": [
                                    {
                                        "user_id": "u-beta",
                                        "first_name": "Beta",
                                        "last_name": "B",
                                        "content": "Beta message",
                                        "created_at": "2024-01-15T10:05:00Z",
                                        "is_ai": False,
                                        "is_current_member": True,
                                    }
                                ],
                                "last_ai_message_at": None,
                            }
                        ],
                    },
                ],
            }
        }
        response = await client.post(
            "/api/v1/messages/webhook", json=payload, headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["groups_affected"] == 2
        assert data["messages_received"] == 2

        result = await db_session.execute(select(Group))
        groups = result.scalars().all()
        assert len(groups) == 2
        group_names = {g.group_name for g in groups}
        assert "Group Alpha" in group_names
        assert "Group Beta" in group_names

    @pytest.mark.asyncio
    async def test_webhook_multiple_threads_in_group(self, client, headers, db_session):
        """Multiple threads in one group are all stored."""
        payload = {
            "payload": {
                "groups_metadata": [{"group_id": 700, "status": "active"}],
                "groups": [
                    {
                        "group_id": 700,
                        "group_name": "Multi-thread Group",
                        "members": [
                            {"user_id": "u-mt", "first_name": "User", "last_name": "MT"}
                        ],
                        "threads": [
                            {
                                "question": {
                                    "id": "q-mt-1",
                                    "text": "Thread 1",
                                    "options": [],
                                    "status": "active",
                                    "unlock_order": 1,
                                },
                                "messages": [
                                    {
                                        "user_id": "u-mt",
                                        "first_name": "User",
                                        "last_name": "MT",
                                        "content": "Thread 1 message",
                                        "created_at": "2024-01-15T10:00:00Z",
                                        "is_ai": False,
                                        "is_current_member": True,
                                    }
                                ],
                                "last_ai_message_at": None,
                            },
                            {
                                "question": {
                                    "id": "q-mt-2",
                                    "text": "Thread 2",
                                    "options": [],
                                    "status": "active",
                                    "unlock_order": 2,
                                },
                                "messages": [
                                    {
                                        "user_id": "u-mt",
                                        "first_name": "User",
                                        "last_name": "MT",
                                        "content": "Thread 2 message",
                                        "created_at": "2024-01-15T10:05:00Z",
                                        "is_ai": False,
                                        "is_current_member": True,
                                    }
                                ],
                                "last_ai_message_at": None,
                            },
                        ],
                    }
                ],
            }
        }
        response = await client.post(
            "/api/v1/messages/webhook", json=payload, headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["question_threads_affected"] == 2
        assert data["messages_received"] == 2

        result = await db_session.execute(select(Message))
        messages = result.scalars().all()
        assert len(messages) == 2
        contents = {m.content for m in messages}
        assert "Thread 1 message" in contents
        assert "Thread 2 message" in contents


# ---------------------------------------------------------------------------
# /api/v1/messages/webhook  — authentication
# ---------------------------------------------------------------------------


class TestWebhookAuth:
    @pytest.mark.asyncio
    async def test_no_api_key_rejected(self, client):
        payload = _make_payload()
        response = await client.post("/api/v1/messages/webhook", json=payload)
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_invalid_api_key_rejected(self, client):
        payload = _make_payload()
        response = await client.post(
            "/api/v1/messages/webhook", json=payload,
            headers={"X-API-Key": "wrong-key"}
        )
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_invalid_payload_returns_422(self, client, headers):
        invalid = {
            "payload": {
                "groups_metadata": [],
                "groups": [
                    {
                        "group_id": "not-an-int",  # should be int
                        "group_name": "Test",
                        "members": [],
                        "threads": [],
                    }
                ],
            }
        }
        response = await client.post("/api/v1/messages/webhook", json=invalid, headers=headers)
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# /api/v1/messages/group_activity
# ---------------------------------------------------------------------------


class TestGroupActivityEndpoint:
    @pytest.mark.asyncio
    async def test_update_group_active_status(self, client, headers, db_session, test_group):
        payload = {"group_id": test_group.external_id, "is_active": False}
        response = await client.patch(
            "/api/v1/messages/group_activity", json=payload, headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["is_active"] is False

        await db_session.refresh(test_group)
        assert test_group.is_active is False

    @pytest.mark.asyncio
    async def test_update_nonexistent_group_returns_404(self, client, headers):
        payload = {"group_id": 99999, "is_active": False}
        response = await client.patch(
            "/api/v1/messages/group_activity", json=payload, headers=headers
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# /api/v1/messages/logs
# ---------------------------------------------------------------------------


class TestGetMessagesEndpoint:
    @pytest.mark.asyncio
    async def test_get_messages_for_group(self, client, headers, test_group, test_messages):
        response = await client.get(
            f"/api/v1/messages/logs?group_id={test_group.external_id}",
            headers=headers,
        )
        assert response.status_code == 200
        messages = response.json()
        assert len(messages) == 5
        assert all("content" in msg for msg in messages)
