"""
Tests for the facilitation decision pipeline.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from app.core.pipeline import FacilitationDecisionPipeline, retry_with_exponential_backoff
from app.services.llm_service import LLMService
from app.models.database import Message


class TestRetryWithExponentialBackoff:
    """Test the retry mechanism."""

    @pytest.mark.asyncio
    async def test_successful_call_no_retry(self):
        """Test that successful calls don't retry."""
        mock_func = AsyncMock(return_value="success")

        result = await retry_with_exponential_backoff(
            mock_func,
            max_retries=3,
            arg1="test"
        )

        assert result == "success"
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test that failures trigger retries."""
        mock_func = AsyncMock(
            side_effect=[Exception("Fail 1"), Exception("Fail 2"), "success"]
        )

        result = await retry_with_exponential_backoff(
            mock_func,
            max_retries=3,
            initial_delay=0.01,  # Short delay for testing
            arg1="test"
        )

        assert result == "success"
        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Test that max retries is respected."""
        mock_func = AsyncMock(side_effect=Exception("Always fail"))

        with pytest.raises(Exception, match="Always fail"):
            await retry_with_exponential_backoff(
                mock_func,
                max_retries=2,
                initial_delay=0.01
            )

        assert mock_func.call_count == 3  # Initial + 2 retries


class TestFacilitationPipeline:
    """Test the facilitation decision pipeline."""

    @pytest.fixture
    def mock_llm_service(self, mock_llm_verification_response, mock_llm_generation_response):
        """Create a mock LLM service."""
        mock_service = MagicMock(spec=LLMService)
        mock_service.verify_facilitation_needed = AsyncMock(
            return_value=mock_llm_verification_response
        )
        mock_service.generate_facilitation_message = AsyncMock(
            return_value=mock_llm_generation_response
        )
        mock_service.format_conversation = MagicMock(
            return_value="[10:00] (1) John: Test message"
        )
        return mock_service

    @pytest.fixture
    def pipeline(self, mock_llm_service):
        """Create a pipeline with mocked LLM service."""
        with patch('app.core.pipeline.joblib.load') as mock_load:
            # Mock the Random Forest model
            mock_rf = MagicMock()
            mock_rf.predict = MagicMock(return_value=[1])  # Predict facilitation needed
            mock_rf.predict_proba = MagicMock(return_value=[[0.3, 0.7]])  # 70% confidence

            mock_load.return_value = {
                'model': mock_rf,
                'feature_names': [
                    'messages_last_30min',
                    'messages_last_hour',
                    'messages_last_3hours',
                    'avg_gap_last_5_messages_min',
                    'time_since_last_message_min'
                ]
            }

            return FacilitationDecisionPipeline(
                llm_service=mock_llm_service,
                model_path="models/temporal_classifier.pkl",
                max_retries=3
            )

    @pytest.mark.asyncio
    async def test_stage1_temporal_classification(self, pipeline, test_messages):
        """Test Stage 1: Temporal feature classification."""
        result = await pipeline.stage1_temporal_classification(test_messages)

        assert 'should_facilitate' in result
        assert 'probability' in result
        assert 'features' in result
        assert isinstance(result['should_facilitate'], bool)
        assert 0 <= result['probability'] <= 1

    @pytest.mark.asyncio
    async def test_stage2_llm_verification(
        self,
        pipeline,
        test_messages,
        mock_llm_verification_response
    ):
        """Test Stage 2: LLM verification."""
        result = await pipeline.stage2_llm_verification(test_messages)

        assert result == mock_llm_verification_response
        assert result['needs_facilitation'] is True
        assert 'reasoning' in result

    @pytest.mark.asyncio
    async def test_stage3_generate_facilitation(
        self,
        pipeline,
        test_messages,
        mock_llm_generation_response
    ):
        """Test Stage 3: Message generation."""
        result = await pipeline.stage3_generate_facilitation(
            test_messages,
            verification_reasoning="Test reasoning"
        )

        assert result == mock_llm_generation_response
        assert 'facilitation_message' in result
        assert 'approach' in result

    @pytest.mark.asyncio
    async def test_complete_pipeline_with_facilitation(
        self,
        pipeline,
        test_messages,
        mock_llm_verification_response,
        mock_llm_generation_response
    ):
        """Test complete pipeline when facilitation is triggered."""
        result = await pipeline.run_pipeline(test_messages)

        # Should go through all 3 stages
        assert result['stage1'] is not None
        assert result['stage2'] is not None
        assert result['stage3'] is not None
        assert result['final_decision'] == 'FACILITATE'
        assert result['facilitation_message'] == mock_llm_generation_response['facilitation_message']

    @pytest.mark.asyncio
    async def test_pipeline_early_termination_stage1(self, pipeline, test_messages):
        """Test pipeline terminates early if Stage 1 says no facilitation."""
        # Mock Stage 1 to return False
        pipeline.rf_model.predict = MagicMock(return_value=[0])  # No facilitation
        pipeline.rf_model.predict_proba = MagicMock(return_value=[[0.8, 0.2]])

        result = await pipeline.run_pipeline(test_messages)

        assert result['stage1'] is not None
        assert result['stage2'] is None  # Should not reach Stage 2
        assert result['stage3'] is None
        assert result['final_decision'] == 'NO_FACILITATION'
        assert result['facilitation_message'] is None

    @pytest.mark.asyncio
    async def test_pipeline_early_termination_stage2(
        self,
        pipeline,
        test_messages,
        mock_llm_no_facilitation_response
    ):
        """Test pipeline terminates early if Stage 2 says no facilitation."""
        # Mock Stage 2 to return False
        pipeline.llm_service.verify_facilitation_needed = AsyncMock(
            return_value=mock_llm_no_facilitation_response
        )

        result = await pipeline.run_pipeline(test_messages)

        assert result['stage1'] is not None
        assert result['stage2'] is not None
        assert result['stage3'] is None  # Should not reach Stage 3
        assert result['final_decision'] == 'NO_FACILITATION_AFTER_VERIFY'
        assert result['facilitation_message'] is None

    @pytest.mark.asyncio
    async def test_pipeline_retry_on_llm_failure(self, pipeline, test_messages):
        """Test that pipeline retries on LLM failures."""
        # Mock LLM to fail twice then succeed
        pipeline.llm_service.verify_facilitation_needed = AsyncMock(
            side_effect=[
                Exception("API Error"),
                Exception("API Error"),
                {
                    "needs_facilitation": True,
                    "reasoning": "Success after retry"
                }
            ]
        )

        result = await pipeline.run_pipeline(test_messages)

        # Should succeed after retries
        assert result['stage2'] is not None
        assert result['stage2']['needs_facilitation'] is True
        assert pipeline.llm_service.verify_facilitation_needed.call_count == 3

    @pytest.mark.asyncio
    async def test_feature_extraction_with_varied_messages(self, pipeline, db_session, test_group, test_user, test_group_question):
        """Test feature extraction with different message patterns."""
        base_time = datetime.now()

        # Create messages with specific timing patterns
        messages = []
        for i in range(10):
            msg = Message(
                group_id=test_group.id,
                group_question_id=test_group_question.id,
                user_id=test_user.id,
                content=f"Message {i}",
                timestamp=base_time - timedelta(minutes=i * 2),
                is_ai=False,
                created_at=datetime.now()
            )
            messages.append(msg)

        # Reverse to get chronological order
        messages.reverse()

        result = await pipeline.stage1_temporal_classification(messages)

        # Verify features are extracted
        features = result['features']
        assert 'messages_last_30min' in features
        assert 'messages_last_hour' in features
        assert 'avg_gap_last_5_messages_min' in features
        assert 'time_since_last_message_min' in features

        # With 2-minute gaps, should have multiple messages in 30min window
        assert features['messages_last_30min'] > 0
