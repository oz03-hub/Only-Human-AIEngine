"""
Tests for the facilitation decision pipeline.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from app.services.facilitator.pipeline import (
    FacilitationDecisionPipeline,
    retry_with_exponential_backoff,
)
from app.services.facilitator.llm_service import LLMService
from app.models.database import Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_STAGE2_YES = {
    "needs_facilitation": True,
    "reasoning": "The conversation shows low engagement.",
    "confidence": 0.85,
}
_MOCK_STAGE2_NO = {
    "needs_facilitation": False,
    "reasoning": "Conversation is active.",
    "confidence": 0.90,
}
_MOCK_STAGE3 = {
    "facilitation_message": "How is everyone doing today?",
    "approach": "Open-ended question",
}
_MOCK_STAGE4_APPROVE = {
    "has_red_flags": False,
    "red_flags_detected": [],
    "severity": "none",
    "reasoning": "No issues detected.",
    "recommendation": "approve",
}
_MOCK_STAGE4_REJECT = {
    "has_red_flags": True,
    "red_flags_detected": ["potentially harmful"],
    "severity": "high",
    "reasoning": "Message contains red flags.",
    "recommendation": "reject",
}


class TestRetryWithExponentialBackoff:
    """Test the retry mechanism."""

    @pytest.mark.asyncio
    async def test_successful_call_no_retry(self):
        """Successful calls don't retry."""
        mock_func = AsyncMock(return_value="success")
        result = await retry_with_exponential_backoff(mock_func, max_retries=3, arg1="test")
        assert result == "success"
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Failures trigger retries."""
        mock_func = AsyncMock(
            side_effect=[Exception("Fail 1"), Exception("Fail 2"), "success"]
        )
        result = await retry_with_exponential_backoff(
            mock_func, max_retries=3, initial_delay=0.01, arg1="test"
        )
        assert result == "success"
        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Max retries is respected; last exception is raised."""
        mock_func = AsyncMock(side_effect=Exception("Always fail"))
        with pytest.raises(Exception, match="Always fail"):
            await retry_with_exponential_backoff(mock_func, max_retries=2, initial_delay=0.01)
        assert mock_func.call_count == 3  # initial + 2 retries


# ---------------------------------------------------------------------------
# Pipeline fixture helpers
# ---------------------------------------------------------------------------


def _make_mock_llm_service(stage2_response=_MOCK_STAGE2_YES):
    mock_service = MagicMock(spec=LLMService)
    mock_service.verify_facilitation_needed = AsyncMock(return_value=stage2_response)
    mock_service.generate_facilitation_message = AsyncMock(return_value=_MOCK_STAGE3)
    mock_service.verify_red_flags = AsyncMock(return_value=_MOCK_STAGE4_APPROVE)
    mock_service.format_conversation = MagicMock(return_value="[10:00] John: Test message")
    return mock_service


def _make_pipeline(mock_llm_service, rf_predict=1, rf_proba=None):
    """Build a FacilitationDecisionPipeline with mocked model + LLM service."""
    if rf_proba is None:
        rf_proba = [[0.3, 0.7]]
    with patch("app.services.facilitator.pipeline.joblib.load") as mock_load:
        mock_rf = MagicMock()
        mock_rf.predict = MagicMock(return_value=[rf_predict])
        mock_rf.predict_proba = MagicMock(return_value=rf_proba)
        mock_load.return_value = {
            "model": mock_rf,
            "feature_names": [
                "messages_last_30min",
                "messages_last_hour",
                "messages_last_3hours",
                "avg_gap_last_5_messages_min",
                "time_since_last_message_min",
            ],
        }
        return FacilitationDecisionPipeline(
            llm_service=mock_llm_service,
            model_path="models/temporal_classifier.pkl",
            max_retries=1,
        )


class TestFacilitationPipeline:
    """Test the facilitation decision pipeline."""

    # --- fixtures -----------------------------------------------------------

    @pytest.fixture
    def mock_llm_service(self):
        return _make_mock_llm_service()

    @pytest.fixture
    def pipeline(self, mock_llm_service):
        return _make_pipeline(mock_llm_service, rf_predict=1)

    # --- stage unit tests ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_stage1_temporal_classification(self, pipeline, test_messages):
        result = await pipeline.stage1_temporal_classification(test_messages)
        assert "should_facilitate" in result
        assert "probability" in result
        assert "features" in result
        assert isinstance(result["should_facilitate"], bool)
        assert 0 <= result["probability"] <= 1

    @pytest.mark.asyncio
    async def test_stage2_llm_verification(self, pipeline, test_messages):
        result = await pipeline.stage2_llm_verification(
            topic="What is your favorite memory?",
            messages=test_messages,
        )
        assert result == _MOCK_STAGE2_YES
        assert result["needs_facilitation"] is True
        assert "reasoning" in result

    @pytest.mark.asyncio
    async def test_stage3_generate_facilitation(self, pipeline, test_messages):
        result = await pipeline.stage3_generate_facilitation(
            topic="What is your favorite memory?",
            messages=test_messages,
            verification_reasoning="Test reasoning",
        )
        assert result == _MOCK_STAGE3
        assert "facilitation_message" in result
        assert "approach" in result

    @pytest.mark.asyncio
    async def test_stage4_verify_red_flags(self, pipeline, test_messages):
        result = await pipeline.stage4_verify_red_flags(
            topic="What is your favorite memory?",
            messages=test_messages,
            facilitation_message="How is everyone doing?",
        )
        assert "has_red_flags" in result
        assert "recommendation" in result

    # --- full pipeline tests ------------------------------------------------

    @pytest.mark.asyncio
    async def test_complete_pipeline_facilitates(self, pipeline, test_messages):
        """Full pipeline triggers facilitation when all stages say yes."""
        result = await pipeline.run_pipeline(
            topic="What is your favorite memory?",
            messages=test_messages,
        )
        assert result["stage1"] is not None
        assert result["stage2"] is not None
        assert result["stage3"] is not None
        assert result["stage4"] is not None
        assert result["final_decision"] == "FACILITATE"
        assert result["facilitation_message"] == _MOCK_STAGE3["facilitation_message"]

    @pytest.mark.asyncio
    async def test_pipeline_early_termination_stage1(self, pipeline, test_messages):
        """Pipeline stops after Stage 1 when RF predicts no facilitation."""
        pipeline.rf_model.predict = MagicMock(return_value=[0])
        pipeline.rf_model.predict_proba = MagicMock(return_value=[[0.8, 0.2]])

        result = await pipeline.run_pipeline(
            topic="What is your favorite memory?",
            messages=test_messages,
        )
        assert result["stage1"] is not None
        assert result["stage2"] is None  # never reached
        assert result["stage3"] is None
        assert result["final_decision"] == "NO_FACILITATION"

    @pytest.mark.asyncio
    async def test_pipeline_early_termination_stage2(self, pipeline, test_messages):
        """Pipeline stops after Stage 2 when LLM says no facilitation."""
        pipeline.llm_service.verify_facilitation_needed = AsyncMock(
            return_value=_MOCK_STAGE2_NO
        )
        result = await pipeline.run_pipeline(
            topic="What is your favorite memory?",
            messages=test_messages,
        )
        assert result["stage1"] is not None
        assert result["stage2"] is not None
        assert result["stage3"] is None  # never reached
        assert result["final_decision"] == "NO_FACILITATION_AFTER_VERIFY"

    @pytest.mark.asyncio
    async def test_pipeline_retry_on_llm_failure(self, pipeline, test_messages):
        """Pipeline retries on LLM failure and eventually succeeds."""
        pipeline.llm_service.verify_facilitation_needed = AsyncMock(
            side_effect=[
                Exception("API Error"),
                _MOCK_STAGE2_YES,
            ]
        )
        result = await pipeline.run_pipeline(
            topic="What is your favorite memory?",
            messages=test_messages,
        )
        assert result["stage2"] is not None
        assert result["stage2"]["needs_facilitation"] is True
        assert pipeline.llm_service.verify_facilitation_needed.call_count == 2

    @pytest.mark.asyncio
    async def test_feature_extraction(
        self, pipeline, db_session, test_group, test_user, test_group_question
    ):
        """Feature extractor produces expected keys from message timing."""
        base_time = datetime.now()
        messages = [
            Message(
                group_id=test_group.id,
                group_question_id=test_group_question.id,
                user_id=test_user.id,
                content=f"Message {i}",
                timestamp=base_time - timedelta(minutes=i * 2),
                is_ai=False,
                created_at=datetime.now(),
            )
            for i in range(10)
        ]
        messages.reverse()

        result = await pipeline.stage1_temporal_classification(messages)
        features = result["features"]
        assert "messages_last_30min" in features
        assert "messages_last_hour" in features
        assert "avg_gap_last_5_messages_min" in features
        assert "time_since_last_message_min" in features
        assert features["messages_last_30min"] > 0


# ---------------------------------------------------------------------------
# Bypass mode tests
# ---------------------------------------------------------------------------


class TestPipelineBypassMode:
    """Verify that bypass=True forces facilitation regardless of stage decisions."""

    @pytest.fixture
    def llm_yes(self):
        return _make_mock_llm_service(stage2_response=_MOCK_STAGE2_YES)

    @pytest.fixture
    def llm_no(self):
        return _make_mock_llm_service(stage2_response=_MOCK_STAGE2_NO)

    @pytest.mark.asyncio
    async def test_bypass_overrides_stage1_no(self, test_messages):
        """bypass=True continues past Stage 1 even when RF says no."""
        svc = _make_mock_llm_service()
        pipeline = _make_pipeline(svc, rf_predict=0, rf_proba=[[0.9, 0.1]])

        result = await pipeline.run_pipeline(
            topic="Test topic",
            messages=test_messages,
            bypass=True,
        )
        # Stage 1 ran (and said no), but we still reached stages 2, 3, 4
        assert result["stage1"] is not None
        assert result["stage1"]["should_facilitate"] is False
        assert result["stage2"] is not None
        assert result["stage3"] is not None
        assert result["stage4"] is not None
        assert result["final_decision"] == "FACILITATE"
        assert result["facilitation_message"] is not None

    @pytest.mark.asyncio
    async def test_bypass_overrides_stage2_no(self, test_messages):
        """bypass=True continues past Stage 2 even when LLM says no."""
        svc = _make_mock_llm_service(stage2_response=_MOCK_STAGE2_NO)
        pipeline = _make_pipeline(svc, rf_predict=1)

        result = await pipeline.run_pipeline(
            topic="Test topic",
            messages=test_messages,
            bypass=True,
        )
        assert result["stage2"] is not None
        assert result["stage2"]["needs_facilitation"] is False
        assert result["stage3"] is not None
        assert result["final_decision"] == "FACILITATE"

    @pytest.mark.asyncio
    async def test_bypass_handles_stage2_exception(self, test_messages):
        """bypass=True continues when Stage 2 raises an exception."""
        svc = _make_mock_llm_service()
        svc.verify_facilitation_needed = AsyncMock(side_effect=Exception("LLM down"))
        pipeline = _make_pipeline(svc, rf_predict=1)

        result = await pipeline.run_pipeline(
            topic="Test topic",
            messages=test_messages,
            bypass=True,
        )
        # Stage 2 failed but we still got a facilitation message
        assert result["stage2"] is not None
        assert result["stage2"]["needs_facilitation"] is True  # default
        assert result["stage3"] is not None
        assert result["final_decision"] == "FACILITATE"

    @pytest.mark.asyncio
    async def test_bypass_handles_stage3_exception(self, test_messages):
        """bypass=True uses fallback message when Stage 3 raises an exception."""
        svc = _make_mock_llm_service()
        svc.generate_facilitation_message = AsyncMock(side_effect=Exception("LLM down"))
        pipeline = _make_pipeline(svc, rf_predict=1)

        result = await pipeline.run_pipeline(
            topic="Test topic",
            messages=test_messages,
            bypass=True,
        )
        assert result["stage3"] is not None
        assert result["final_decision"] == "FACILITATE"
        assert result["facilitation_message"] is not None

    @pytest.mark.asyncio
    async def test_bypass_handles_stage4_exception(self, test_messages):
        """bypass=True approves message when Stage 4 raises an exception."""
        svc = _make_mock_llm_service()
        svc.verify_red_flags = AsyncMock(side_effect=Exception("LLM down"))
        pipeline = _make_pipeline(svc, rf_predict=1)

        result = await pipeline.run_pipeline(
            topic="Test topic",
            messages=test_messages,
            bypass=True,
        )
        assert result["stage4"] is not None
        assert result["final_decision"] == "FACILITATE"

    @pytest.mark.asyncio
    async def test_no_bypass_stage1_no_stops_pipeline(self, test_messages):
        """Without bypass, Stage 1 negative stops the pipeline (regression guard)."""
        svc = _make_mock_llm_service()
        pipeline = _make_pipeline(svc, rf_predict=0, rf_proba=[[0.9, 0.1]])

        result = await pipeline.run_pipeline(
            topic="Test topic",
            messages=test_messages,
        )
        assert result["stage2"] is None
        assert result["final_decision"] == "NO_FACILITATION"
