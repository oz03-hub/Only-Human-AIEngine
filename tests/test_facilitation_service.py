"""
Tests for the facilitation service.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.facilitation_service import FacilitationService
from app.models.database import Group, GroupQuestion, FacilitationLog, User, Message, Question


# ---------------------------------------------------------------------------
# Shared pipeline mock
# ---------------------------------------------------------------------------

_FACILITATE_RESULT = {
    "stage1": {"should_facilitate": True, "probability": 0.8, "features": {}},
    "stage2": {"needs_facilitation": True, "reasoning": "Low engagement"},
    "stage3": {"facilitation_message": "How is everyone doing?", "approach": "Open question"},
    "stage4": {"has_red_flags": False, "recommendation": "approve"},
    "final_decision": "FACILITATE",
    "facilitation_message": "How is everyone doing?",
}

_NO_FACILITATION_RESULT = {
    "stage1": {"should_facilitate": False, "probability": 0.2, "features": {}},
    "stage2": None,
    "stage3": None,
    "stage4": None,
    "final_decision": "NO_FACILITATION",
    "facilitation_message": None,
}


@pytest_asyncio.fixture
async def facilitation_service(db_session):
    """FacilitationService with the pipeline mocked out."""
    mock_pipeline = MagicMock()
    mock_pipeline.run_pipeline = AsyncMock(return_value=_FACILITATE_RESULT)
    yield FacilitationService(db_session, mock_pipeline)


# ---------------------------------------------------------------------------
# process_webhook_messages tests
# ---------------------------------------------------------------------------


class TestProcessWebhookMessages:
    """Tests for FacilitationService.process_webhook_messages."""

    @pytest.mark.asyncio
    async def test_facilitate_single_thread(
        self, facilitation_service, test_group, test_question, test_messages
    ):
        """Returns facilitation response when pipeline decides to facilitate."""
        pairs = [(test_group.external_id, test_question.external_id)]
        responses = await facilitation_service.process_webhook_messages(pairs)

        assert len(responses) == 1
        assert responses[0]["group_id"] == test_group.external_id
        assert responses[0]["question_id"] == test_question.external_id
        assert responses[0]["message"] == "How is everyone doing?"

    @pytest.mark.asyncio
    async def test_no_facilitation_returns_empty(
        self, facilitation_service, test_group, test_question, test_messages
    ):
        """Returns empty list when pipeline decides not to facilitate."""
        facilitation_service.pipeline.run_pipeline = AsyncMock(
            return_value=_NO_FACILITATION_RESULT
        )
        pairs = [(test_group.external_id, test_question.external_id)]
        responses = await facilitation_service.process_webhook_messages(pairs)

        assert responses == []

    @pytest.mark.asyncio
    async def test_nonexistent_group_skipped(self, facilitation_service):
        """Non-existent groups are skipped without error."""
        pairs = [(99999, "no-such-question")]
        responses = await facilitation_service.process_webhook_messages(pairs)
        assert responses == []

    @pytest.mark.asyncio
    async def test_multiple_threads(
        self, facilitation_service, db_session, test_group, test_user
    ):
        """Facilitates multiple threads in one call."""
        q1 = Question(external_id="q-multi-1", text="Question 1")
        q2 = Question(external_id="q-multi-2", text="Question 2")
        db_session.add_all([q1, q2])
        await db_session.flush()

        gq1 = GroupQuestion(
            group_id=test_group.id, question_id=q1.id,
            status="active", unlock_order=1, created_at=datetime.now(),
        )
        gq2 = GroupQuestion(
            group_id=test_group.id, question_id=q2.id,
            status="active", unlock_order=2, created_at=datetime.now(),
        )
        db_session.add_all([gq1, gq2])
        await db_session.flush()

        for gq in [gq1, gq2]:
            for i in range(6):
                db_session.add(Message(
                    group_id=test_group.id,
                    group_question_id=gq.id,
                    user_id=test_user.id,
                    content=f"Message {i}",
                    timestamp=datetime.now(),
                    is_ai=False,
                    created_at=datetime.now(),
                ))
        await db_session.flush()

        pairs = [
            (test_group.external_id, "q-multi-1"),
            (test_group.external_id, "q-multi-2"),
        ]
        responses = await facilitation_service.process_webhook_messages(pairs)

        assert len(responses) == 2
        assert all(r["message"] == "How is everyone doing?" for r in responses)

    @pytest.mark.asyncio
    async def test_insufficient_messages_skipped(
        self, facilitation_service, test_group, test_question
    ):
        """Thread with fewer messages than min_messages is skipped (no pipeline call)."""
        # test_question thread has no messages (we haven't added test_messages fixture)
        pairs = [(test_group.external_id, test_question.external_id)]
        responses = await facilitation_service.process_webhook_messages(pairs)

        # Pipeline should not have been called
        facilitation_service.pipeline.run_pipeline.assert_not_called()
        assert responses == []

    @pytest.mark.asyncio
    async def test_facilitation_log_created(
        self, facilitation_service, db_session, test_group, test_question, test_messages
    ):
        """A FacilitationLog row is written to the DB after pipeline runs."""
        pairs = [(test_group.external_id, test_question.external_id)]
        await facilitation_service.process_webhook_messages(pairs)

        result = await db_session.execute(select(FacilitationLog))
        logs = result.scalars().all()
        assert len(logs) == 1
        log = logs[0]
        assert log.group_id == test_group.id
        assert log.final_decision.value == "FACILITATE"
        assert log.facilitation_message == "How is everyone doing?"
        assert log.stage1_result is not None
        assert log.stage2_result is not None
        assert log.stage3_result is not None

    @pytest.mark.asyncio
    async def test_no_facilitation_log_has_no_sent_at(
        self, facilitation_service, db_session, test_group, test_question, test_messages
    ):
        """When pipeline returns NO_FACILITATION, message_sent_at is None in the log."""
        facilitation_service.pipeline.run_pipeline = AsyncMock(
            return_value=_NO_FACILITATION_RESULT
        )
        pairs = [(test_group.external_id, test_question.external_id)]
        await facilitation_service.process_webhook_messages(pairs)

        result = await db_session.execute(select(FacilitationLog))
        logs = result.scalars().all()
        assert len(logs) == 1
        assert logs[0].message_sent_at is None

    @pytest.mark.asyncio
    async def test_pipeline_exception_does_not_crash_service(
        self, facilitation_service, test_group, test_question, test_messages
    ):
        """An exception inside the pipeline is caught and the method returns gracefully."""
        facilitation_service.pipeline.run_pipeline = AsyncMock(
            side_effect=Exception("Unexpected pipeline error")
        )
        pairs = [(test_group.external_id, test_question.external_id)]
        # Should not raise
        responses = await facilitation_service.process_webhook_messages(pairs)
        assert responses == []
