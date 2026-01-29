"""
Tests for the facilitation service.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.facilitation_service import FacilitationService
from app.services.message_service import MessageService
from app.core.pipeline import FacilitationDecisionPipeline
from app.models.database import Group, GroupQuestion, FacilitationLog, User, Message


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


class TestFacilitationPipelineIntegration:
    """Integration tests for the full facilitation pipeline (no mocks)."""

    @pytest_asyncio.fixture
    async def real_facilitation_service(self, db_session):
        """Create facilitation service with real pipeline (no mocking)."""
        from app.services.facilitation_service import FacilitationService
        service = FacilitationService(db_session)
        yield service

    @pytest_asyncio.fixture
    async def longer_conversation(
        self,
        db_session: AsyncSession,
        test_group: Group,
        test_group_question: GroupQuestion,
    ):
        """Create a longer, realistic conversation for integration testing."""
        # Create multiple users
        users = []
        user_names = [
            ("Alice", "Johnson"),
            ("Bob", "Smith"),
            ("Charlie", "Brown"),
            ("Diana", "Martinez"),
        ]

        for i, (first_name, last_name) in enumerate(user_names):
            user = User(
                external_user_id=f"user-{i+1}",
                first_name=first_name,
                last_name=last_name,
                created_at=datetime.now()
            )
            db_session.add(user)
            users.append(user)

        await db_session.flush()

        # Create a realistic conversation about climate change with various patterns
        base_time = datetime.now() - timedelta(hours=2)
        messages = []

        conversation_data = [
            (0, 0, "I've been thinking a lot about climate change lately. It's really overwhelming."),
            (1, 5, "I feel the same way. Sometimes I don't know where to start making a difference."),
            (2, 8, "Have any of you made lifestyle changes to reduce your carbon footprint?"),
            (0, 12, "I've started composting and using public transit more often."),
            (3, 15, "That's great! I've been trying to reduce single-use plastics."),
            (1, 18, "I installed solar panels last year. It was expensive but worth it."),
            (2, 22, "Wow, solar panels! That's a big commitment. How much did it help with your energy bills?"),
            (1, 25, "My bills dropped by about 60%. Plus there are tax incentives."),
            (0, 30, "That's impressive. I wish more people knew about these options."),
            (3, 35, "The challenge is that not everyone can afford the upfront costs."),
            (2, 40, "True. But even small changes add up, right?"),
            (1, 45, "Absolutely. Every little bit helps."),
            (0, 55, "I've also been educating my kids about environmental issues."),
            (3, 60, "That's so important. The next generation needs to be informed."),
            (2, 70, "Does anyone else feel anxious about the future of our planet?"),
            (0, 75, "All the time. It keeps me up at night sometimes."),
            (1, 80, "I try to focus on what I can control rather than the big picture."),
            (3, 85, "That's a healthy approach. We can't solve everything alone."),
            (2, 95, "You're right. Maybe we should organize a community cleanup event?"),
            (0, 100, "I'd be interested in that! Let me know if you set something up."),
        ]

        for user_idx, minutes_offset, content in conversation_data:
            msg = Message(
                group_id=test_group.id,
                group_question_id=test_group_question.id,
                user_id=users[user_idx].id,
                content=content,
                timestamp=base_time + timedelta(minutes=minutes_offset),
                is_ai=False,
                created_at=datetime.now()
            )
            db_session.add(msg)
            messages.append(msg)

        await db_session.flush()

        # Refresh messages to load relationships
        for msg in messages:
            await db_session.refresh(msg, ['user'])

        return messages

    @pytest.mark.asyncio
    async def test_full_pipeline_execution_longer_conversation(
        self,
        real_facilitation_service,
        test_group,
        test_group_question,
        longer_conversation,
        db_session
    ):
        """
        Integration test: Run the full pipeline on a longer conversation.

        This test verifies that the entire pipeline executes without errors:
        - Stage 1: Random Forest temporal classification
        - Stage 2: LLM verification (calls OpenAI API)
        - Stage 3: LLM message generation (calls OpenAI API)

        The actual decision result doesn't matter - we just want to ensure
        the pipeline completes successfully without exceptions.
        """
        # Run the full facilitation check with real pipeline
        result = await real_facilitation_service.check_and_facilitate(
            test_group,
            test_group_question,
            min_messages=5,  # We have 20 messages, so this will pass
            limit_messages=10
        )

        # Verify the pipeline completed successfully
        assert result is not None
        assert 'decision' in result
        assert 'pipeline_result' in result

        # Verify pipeline result structure
        pipeline_result = result['pipeline_result']
        assert 'stage1' in pipeline_result
        assert 'final_decision' in pipeline_result

        # Stage 1 should always run
        assert pipeline_result['stage1'] is not None
        assert 'should_facilitate' in pipeline_result['stage1']
        assert 'probability' in pipeline_result['stage1']
        assert 'features' in pipeline_result['stage1']

        # Verify features were extracted
        features = pipeline_result['stage1']['features']
        assert 'messages_last_30min' in features
        assert 'messages_last_hour' in features
        assert 'time_since_last_message_min' in features

        # If stage1 decided to facilitate, stage2 should have run
        if pipeline_result['stage1']['should_facilitate']:
            assert pipeline_result['stage2'] is not None
            assert 'needs_facilitation' in pipeline_result['stage2']
            assert 'reasoning' in pipeline_result['stage2']

            # If stage2 also said yes, stage3 should have run
            if pipeline_result['stage2']['needs_facilitation']:
                assert pipeline_result['stage3'] is not None
                assert 'facilitation_message' in pipeline_result['stage3']
                assert 'approach' in pipeline_result['stage3']
                assert pipeline_result['final_decision'] == 'FACILITATE'
                assert result['message'] is not None
            else:
                # Stage2 said no, stage3 shouldn't run
                assert pipeline_result['stage3'] is None
                assert result['message'] is None
        else:
            # Stage1 said no, stages 2 and 3 shouldn't run
            assert pipeline_result['stage2'] is None
            assert pipeline_result['stage3'] is None
            assert result['message'] is None

        # Verify a log was created
        assert result['log_id'] is not None

        # Verify the log was actually saved to the database
        from sqlalchemy import select
        log_result = await db_session.execute(
            select(FacilitationLog).where(FacilitationLog.id == result['log_id'])
        )
        log = log_result.scalar_one()

        assert log is not None
        assert log.group_id == test_group.id
        assert log.group_question_id == test_group_question.id
        assert log.stage1_result is not None

        # Success - the pipeline executed without errors!

    @pytest.mark.asyncio
    async def test_full_pipeline_execution_conflict_conversation(
        self,
        real_facilitation_service,
        test_group,
        test_group_question,
        db_session
    ):
        """
        Integration test: Run pipeline on a conversation with conflict patterns.

        This tests a different conversation pattern with disagreement and tension
        to see how the pipeline handles various conversation dynamics.
        """
        # Create users
        users = []
        for i in range(3):
            user = User(
                external_user_id=f"conflict-user-{i+1}",
                first_name=f"User{i+1}",
                last_name="Test",
                created_at=datetime.now()
            )
            db_session.add(user)
            users.append(user)

        await db_session.flush()

        # Create a conversation with conflict and tension
        base_time = datetime.now() - timedelta(hours=1)
        messages = []

        conversation_data = [
            (0, 0, "I think we should focus on economic growth first."),
            (1, 3, "I strongly disagree. Environmental protection should be the priority."),
            (0, 5, "But without economic stability, we can't afford environmental programs."),
            (1, 7, "That's shortsighted. We won't have an economy if we destroy the planet."),
            (2, 10, "Both perspectives have merit. Can we find a middle ground?"),
            (0, 12, "I'm not sure there is a middle ground here."),
            (1, 14, "Exactly. This is too important to compromise on."),
            (2, 18, "Maybe we're looking at this the wrong way..."),
            (0, 22, "What do you mean?"),
            (1, 25, "Yeah, I'm curious what you're thinking."),
            (2, 28, "What if we considered policies that address both concerns simultaneously?"),
            (0, 32, "Like what?"),
            (2, 35, "Green jobs programs, for example. They create economic opportunity while helping the environment."),
            (1, 38, "That's actually a good point."),
            (0, 40, "I could get behind something like that."),
        ]

        for user_idx, minutes_offset, content in conversation_data:
            msg = Message(
                group_id=test_group.id,
                group_question_id=test_group_question.id,
                user_id=users[user_idx].id,
                content=content,
                timestamp=base_time + timedelta(minutes=minutes_offset),
                is_ai=False,
                created_at=datetime.now()
            )
            db_session.add(msg)
            messages.append(msg)

        await db_session.flush()

        for msg in messages:
            await db_session.refresh(msg, ['user'])

        # Run the pipeline
        result = await real_facilitation_service.check_and_facilitate(
            test_group,
            test_group_question,
            min_messages=5,
            limit_messages=10
        )

        # Verify completion without errors
        assert result is not None
        assert 'decision' in result
        assert 'pipeline_result' in result
        assert result['log_id'] is not None

        # Verify log was saved
        from sqlalchemy import select
        log_result = await db_session.execute(
            select(FacilitationLog).where(FacilitationLog.id == result['log_id'])
        )
        log = log_result.scalar_one()
        assert log is not None

        # Success - pipeline handled conflict conversation without errors!
