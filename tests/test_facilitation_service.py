"""
Tests for the facilitation service.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.services.facilitation_service import FacilitationService
from app.services.message_service import MessageService
from app.core.pipeline import FacilitationDecisionPipeline
from app.models.database import Group, GroupQuestion, FacilitationLog


class TestFacilitationService:
    """Test the facilitation service."""

    @pytest_asyncio.fixture
    async def facilitation_service(self, db_session):
        """Create facilitation service with mocked pipeline."""
        with patch('app.services.facilitation_service.FacilitationDecisionPipeline') as mock_pipeline_class:
            mock_pipeline = MagicMock()
            mock_pipeline.run_pipeline = AsyncMock()
            mock_pipeline_class.return_value = mock_pipeline

            service = FacilitationService(db_session)
            service.pipeline = mock_pipeline
            yield service

    @pytest.mark.asyncio
    async def test_check_and_facilitate_success(
        self,
        facilitation_service,
        test_group,
        test_group_question,
        test_messages
    ):
        """Test successful facilitation check."""
        # Mock pipeline result
        facilitation_service.pipeline.run_pipeline.return_value = {
            'stage1': {'should_facilitate': True, 'probability': 0.7},
            'stage2': {'needs_facilitation': True, 'reasoning': 'Test'},
            'stage3': {
                'facilitation_message': 'How is everyone doing?',
                'approach': 'Open-ended question'
            },
            'final_decision': 'FACILITATE',
            'facilitation_message': 'How is everyone doing?'
        }

        result = await facilitation_service.check_and_facilitate(
            test_group,
            test_group_question,
            min_messages=3
        )

        assert result['decision'] == 'FACILITATE'
        assert result['message'] == 'How is everyone doing?'
        assert result['log_id'] is not None

    @pytest.mark.asyncio
    async def test_check_and_facilitate_insufficient_messages(
        self,
        facilitation_service,
        test_group,
        test_group_question,
        db_session
    ):
        """Test that facilitation is skipped with insufficient messages."""
        # Don't create any messages, just use empty conversation
        result = await facilitation_service.check_and_facilitate(
            test_group,
            test_group_question,
            min_messages=5
        )

        assert result['decision'] == 'NO_FACILITATION'
        assert result['message'] is None
        assert 'Insufficient messages' in result['reason']
        assert result['log_id'] is None

    @pytest.mark.asyncio
    async def test_check_and_facilitate_no_facilitation_stage1(
        self,
        facilitation_service,
        test_group,
        test_group_question,
        test_messages
    ):
        """Test when Stage 1 determines no facilitation needed."""
        facilitation_service.pipeline.run_pipeline.return_value = {
            'stage1': {'should_facilitate': False, 'probability': 0.2},
            'stage2': None,
            'stage3': None,
            'final_decision': 'NO_FACILITATION',
            'facilitation_message': None
        }

        result = await facilitation_service.check_and_facilitate(
            test_group,
            test_group_question,
            min_messages=3
        )

        assert result['decision'] == 'NO_FACILITATION'
        assert result['message'] is None
        assert result['log_id'] is not None  # Log should still be created

    @pytest.mark.asyncio
    async def test_check_and_facilitate_creates_log(
        self,
        facilitation_service,
        test_group,
        test_group_question,
        test_messages,
        db_session
    ):
        """Test that facilitation log is created."""
        facilitation_service.pipeline.run_pipeline.return_value = {
            'stage1': {'should_facilitate': True, 'probability': 0.8},
            'stage2': {'needs_facilitation': True, 'reasoning': 'Test'},
            'stage3': {
                'facilitation_message': 'Test message',
                'approach': 'Test approach'
            },
            'final_decision': 'FACILITATE',
            'facilitation_message': 'Test message'
        }

        result = await facilitation_service.check_and_facilitate(
            test_group,
            test_group_question
        )

        # Verify log was created
        log_id = result['log_id']
        assert log_id is not None

        # Query the log from database
        from sqlalchemy import select
        log_result = await db_session.execute(
            select(FacilitationLog).where(FacilitationLog.id == log_id)
        )
        log = log_result.scalar_one()

        assert log.group_id == test_group.id
        assert log.group_question_id == test_group_question.id
        assert log.final_decision.value == 'FACILITATE'
        assert log.facilitation_message == 'Test message'
        assert log.stage1_result is not None
        assert log.stage2_result is not None
        assert log.stage3_result is not None

    @pytest.mark.asyncio
    async def test_process_webhook_messages_single_thread(
        self,
        facilitation_service,
        test_group,
        test_question,
        test_messages
    ):
        """Test processing webhook messages for a single thread."""
        facilitation_service.pipeline.run_pipeline.return_value = {
            'stage1': {'should_facilitate': True, 'probability': 0.8},
            'stage2': {'needs_facilitation': True, 'reasoning': 'Test'},
            'stage3': {
                'facilitation_message': 'Great discussion!',
                'approach': 'Positive reinforcement'
            },
            'final_decision': 'FACILITATE',
            'facilitation_message': 'Great discussion!'
        }

        group_question_pairs = [
            (test_group.external_id, test_question.external_id)
        ]

        responses = await facilitation_service.process_webhook_messages(
            group_question_pairs
        )

        assert len(responses) == 1
        assert responses[0]['group_id'] == test_group.external_id
        assert responses[0]['question_id'] == test_question.external_id
        assert responses[0]['message'] == 'Great discussion!'

    @pytest.mark.asyncio
    async def test_process_webhook_messages_multiple_threads(
        self,
        facilitation_service,
        db_session,
        test_group,
        test_user
    ):
        """Test processing webhook messages for multiple threads."""
        from app.models.database import Question, GroupQuestion, Message

        # Create two questions
        question1 = Question(external_id="q1", text="Question 1")
        question2 = Question(external_id="q2", text="Question 2")
        db_session.add_all([question1, question2])
        await db_session.flush()

        # Create two group-question threads
        gq1 = GroupQuestion(
            group_id=test_group.id,
            question_id=question1.id,
            status="active",
            unlock_order=1,
            created_at=datetime.now()
        )
        gq2 = GroupQuestion(
            group_id=test_group.id,
            question_id=question2.id,
            status="active",
            unlock_order=2,
            created_at=datetime.now()
        )
        db_session.add_all([gq1, gq2])
        await db_session.flush()

        # Create messages for each thread
        for gq in [gq1, gq2]:
            for i in range(5):
                msg = Message(
                    group_id=test_group.id,
                    group_question_id=gq.id,
                    user_id=test_user.id,
                    content=f"Message {i}",
                    timestamp=datetime.now(),
                    is_ai=False,
                    created_at=datetime.now()
                )
                db_session.add(msg)
        await db_session.flush()

        # Mock pipeline to facilitate for both
        facilitation_service.pipeline.run_pipeline.return_value = {
            'stage1': {'should_facilitate': True, 'probability': 0.8},
            'stage2': {'needs_facilitation': True, 'reasoning': 'Test'},
            'stage3': {
                'facilitation_message': 'Test message',
                'approach': 'Test'
            },
            'final_decision': 'FACILITATE',
            'facilitation_message': 'Test message'
        }

        group_question_pairs = [
            (test_group.external_id, "q1"),
            (test_group.external_id, "q2")
        ]

        responses = await facilitation_service.process_webhook_messages(
            group_question_pairs
        )

        assert len(responses) == 2
        assert all(r['message'] == 'Test message' for r in responses)

    @pytest.mark.asyncio
    async def test_process_webhook_messages_skip_nonexistent_group(
        self,
        facilitation_service
    ):
        """Test that nonexistent groups are skipped gracefully."""
        group_question_pairs = [
            (99999, "nonexistent-question")  # Nonexistent group
        ]

        responses = await facilitation_service.process_webhook_messages(
            group_question_pairs
        )

        # Should return empty list without errors
        assert len(responses) == 0

    @pytest.mark.asyncio
    async def test_process_webhook_messages_no_facilitation_needed(
        self,
        facilitation_service,
        test_group,
        test_question,
        test_messages
    ):
        """Test processing when no facilitation is needed."""
        facilitation_service.pipeline.run_pipeline.return_value = {
            'stage1': {'should_facilitate': False, 'probability': 0.2},
            'stage2': None,
            'stage3': None,
            'final_decision': 'NO_FACILITATION',
            'facilitation_message': None
        }

        group_question_pairs = [
            (test_group.external_id, test_question.external_id)
        ]

        responses = await facilitation_service.process_webhook_messages(
            group_question_pairs
        )

        # Should return empty list when no facilitation needed
        assert len(responses) == 0

    @pytest.mark.asyncio
    async def test_get_thread_facilitation_logs(
        self,
        facilitation_service,
        test_group,
        test_group_question,
        test_messages,
        db_session
    ):
        """Test retrieving facilitation logs for a thread."""
        # Create a facilitation log
        log = FacilitationLog(
            group_id=test_group.id,
            group_question_id=test_group_question.id,
            triggered_at=datetime.now(),
            stage1_result={'test': 'data'},
            stage2_result={'test': 'data'},
            stage3_result={'test': 'data'},
            final_decision='FACILITATE',
            facilitation_message='Test message',
            message_sent_at=datetime.now()
        )
        db_session.add(log)
        await db_session.flush()

        logs = await facilitation_service.get_thread_facilitation_logs(
            test_group,
            test_group_question,
            limit=10
        )

        assert len(logs) == 1
        assert logs[0]['final_decision'] == 'FACILITATE'
        assert logs[0]['facilitation_message'] == 'Test message'
