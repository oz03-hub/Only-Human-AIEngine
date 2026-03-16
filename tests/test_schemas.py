"""
Tests for Pydantic webhook schema parsing and validation.
Covers the actual payload format from webhookschema.json.
"""

import pytest
from datetime import datetime

from app.models.schemas import (
    WebhookIncomingRequest,
    WebhookIncomingThread,
    WebhookIncomingMessage,
    WebhookIncomingGroupMetadata,
    WebhookIncomingGroupMember,
)


# ===== Fixture: minimal valid payload =====


@pytest.fixture
def minimal_payload():
    """Minimal valid webhook payload matching webhookschema.json structure."""
    return {
        "payload": {
            "groups_metadata": [
                {
                    "group_id": 4,
                    "status": "active",
                    "status_updated_at": "2026-02-20T10:00:00Z",
                },
                {"group_id": 2, "status": "pending", "status_updated_at": None},
            ],
            "groups": [
                {
                    "group_id": 2,
                    "group_name": "Item 2 Chat",
                    "members": [
                        {
                            "user_id": "e1000000-e5ef-4758-a0e3-e19a009b2853",
                            "first_name": "Cristina",
                            "last_name": None,
                        },
                        {
                            "user_id": "50000000-780a-473c-91fc-b0043688eefc",
                            "first_name": "Michelle",
                            "last_name": None,
                        },
                    ],
                    "threads": [
                        {
                            "question": {
                                "id": "f0000000-3e89-481e-b3f6-7082fdae2af5",
                                "text": "Do your feelings of responsibility to others help you?",
                                "options": [
                                    "Helps me . . .",
                                    "Burdens me . . .",
                                    "Actually . . .",
                                ],
                                "status": "active",
                                "unlock_order": 3,
                            },
                            "messages": [
                                {
                                    "user_id": "e1000000-e5ef-4758-a0e3-e19a009b2853",
                                    "first_name": "Cristina",
                                    "last_name": None,
                                    "content": "<highlight>Burdens me . . .</highlight> pressure",
                                    "created_at": "2026-02-16 08:56:44.292422+00",
                                    "is_ai": False,
                                    "is_current_member": True,
                                },
                                {
                                    "user_id": "50000000-780a-473c-91fc-b0043688eefc",
                                    "first_name": "Michelle",
                                    "last_name": None,
                                    "content": "Not really sure",
                                    "created_at": "2026-02-16 09:26:54.603133+00",
                                    "is_ai": False,
                                    "is_current_member": True,
                                },
                            ],
                            "last_ai_message_at": None,
                        },
                        {
                            "question": {
                                "id": "c0000000-4a07-4112-a8f4-bbad84e30950",
                                "text": "A pending question",
                                "options": [],
                                "status": "pending",
                                "unlock_order": 4,
                            },
                            "messages": [],
                            "last_ai_message_at": None,
                        },
                    ],
                }
            ],
        }
    }


# ===== Schema parsing tests =====


class TestWebhookSchemaParses:
    def test_groups_metadata_count(self, minimal_payload):
        req = WebhookIncomingRequest.model_validate(minimal_payload)
        assert len(req.payload.groups_metadata) == 2

    def test_groups_metadata_status(self, minimal_payload):
        req = WebhookIncomingRequest.model_validate(minimal_payload)
        statuses = {m.group_id: m.status for m in req.payload.groups_metadata}
        assert statuses[4] == "active"
        assert statuses[2] == "pending"

    def test_groups_metadata_optional_timestamp(self, minimal_payload):
        req = WebhookIncomingRequest.model_validate(minimal_payload)
        meta = {m.group_id: m for m in req.payload.groups_metadata}
        assert meta[4].status_updated_at is not None
        assert meta[2].status_updated_at is None

    def test_group_threads_count(self, minimal_payload):
        req = WebhookIncomingRequest.model_validate(minimal_payload)
        assert len(req.payload.groups[0].threads) == 2

    def test_members_parsed(self, minimal_payload):
        req = WebhookIncomingRequest.model_validate(minimal_payload)
        members = req.payload.groups[0].members
        assert len(members) == 2
        assert members[0].first_name == "Cristina"
        assert members[0].last_name is None

    def test_question_fields(self, minimal_payload):
        req = WebhookIncomingRequest.model_validate(minimal_payload)
        q = req.payload.groups[0].threads[0].question
        assert q.id == "f0000000-3e89-481e-b3f6-7082fdae2af5"
        assert q.status == "active"
        assert q.unlock_order == 3
        assert len(q.options) == 3

    def test_message_fields(self, minimal_payload):
        req = WebhookIncomingRequest.model_validate(minimal_payload)
        msg = req.payload.groups[0].threads[0].messages[0]
        assert msg.user_id == "e1000000-e5ef-4758-a0e3-e19a009b2853"
        assert msg.is_ai is False
        assert msg.is_current_member is True
        assert isinstance(msg.created_at, datetime)


class TestTimezoneNormalization:
    """Timestamp format from the real app uses +00 instead of +00:00 — must parse correctly."""

    def test_short_utc_offset(self):
        msg = WebhookIncomingMessage.model_validate(
            {
                "user_id": "abc",
                "content": "hello",
                "created_at": "2026-02-16 08:56:44.292422+00",
                "is_ai": False,
            }
        )
        assert isinstance(msg.created_at, datetime)

    def test_standard_iso_format_still_works(self):
        msg = WebhookIncomingMessage.model_validate(
            {
                "user_id": "abc",
                "content": "hello",
                "created_at": "2026-02-16T10:00:00Z",
                "is_ai": False,
            }
        )
        assert isinstance(msg.created_at, datetime)


class TestOptionalFields:
    def test_member_null_names(self):
        member = WebhookIncomingGroupMember.model_validate(
            {
                "user_id": "abc",
                "first_name": None,
                "last_name": None,
            }
        )
        assert member.first_name is None
        assert member.last_name is None

    def test_message_null_names(self):
        msg = WebhookIncomingMessage.model_validate(
            {
                "user_id": "abc",
                "first_name": None,
                "last_name": None,
                "content": "hi",
                "created_at": "2026-02-16T10:00:00Z",
                "is_ai": False,
            }
        )
        assert msg.first_name is None
        assert msg.last_name is None

    def test_is_current_member_defaults_true(self):
        msg = WebhookIncomingMessage.model_validate(
            {
                "user_id": "abc",
                "content": "hi",
                "created_at": "2026-02-16T10:00:00Z",
                "is_ai": False,
            }
        )
        assert msg.is_current_member is True

    def test_thread_last_ai_message_at_optional(self):
        thread = WebhookIncomingThread.model_validate(
            {
                "question": {
                    "id": "q1",
                    "text": "test",
                    "options": [],
                    "status": "active",
                    "unlock_order": 1,
                },
                "messages": [],
            }
        )
        assert thread.last_ai_message_at is None

class TestEmptyGroups:
    """Groups with empty members/threads (as seen in webhookschema.json) should parse fine."""

    def test_empty_group(self):
        payload = {
            "payload": {
                "groups_metadata": [{"group_id": 4, "status": "active"}],
                "groups": [
                    {
                        "group_id": 4,
                        "group_name": "Item 4 Chat",
                        "members": [],
                        "threads": [],
                    }
                ],
            }
        }
        req = WebhookIncomingRequest.model_validate(payload)
        assert req.payload.groups[0].threads == []
        assert req.payload.groups[0].members == []


class TestActiveThreadExtraction:
    """The webhook route filters active threads for facilitation."""

    def test_only_active_threads_selected(self, minimal_payload):
        req = WebhookIncomingRequest.model_validate(minimal_payload)
        active_pairs = {
            (group.group_id, thread.question.id)
            for group in req.payload.groups
            for thread in group.threads
            if thread.question.status == "active"
        }
        # Only the active thread should be selected, not the pending one
        assert len(active_pairs) == 1
        assert (2, "f0000000-3e89-481e-b3f6-7082fdae2af5") in active_pairs
