"""
Multi-stage facilitation decision pipeline.
Implements the 3-stage decision process with early termination.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Callable, TypeVar
import joblib
import numpy as np

from app.config import settings
from app.models.database import Message
from app.core.feature_extractor import TemporalFeatureExtractor
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

T = TypeVar('T')


async def retry_with_exponential_backoff(
    func: Callable[..., T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 10.0,
    exponential_base: float = 2.0,
    *args,
    **kwargs
) -> T:
    """
    Retry an async function with exponential backoff.

    Args:
        func: Async function to retry
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        Result from func

    Raises:
        Exception: Last exception if all retries fail
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e

            if attempt == max_retries:
                logger.error(
                    f"Failed after {max_retries} retries. Last error: {e}",
                    exc_info=True
                )
                raise

            # Calculate delay with exponential backoff
            delay = min(initial_delay * (exponential_base ** attempt), max_delay)

            logger.warning(
                f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                f"Retrying in {delay:.1f}s..."
            )

            await asyncio.sleep(delay)

    # Should never reach here, but for type safety
    if last_exception:
        raise last_exception


class FacilitationDecisionPipeline:
    """Multi-stage decision pipeline for chat facilitation."""

    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        model_path: Optional[str] = None,
        max_retries: int = 3
    ):
        """
        Initialize the facilitation pipeline.

        Args:
            llm_service: LLM service instance (creates new one if not provided)
            model_path: Path to trained Random Forest classifier
            max_retries: Maximum number of retries for LLM calls (default: 3)
        """
        self.llm_service = llm_service or LLMService()
        self.model_path = model_path or settings.model_path
        self.max_retries = max_retries

        # Load the trained Random Forest model
        logger.info(f"Loading trained model from {self.model_path}...")
        model_data = joblib.load(self.model_path)
        self.rf_model = model_data['model']
        self.feature_names = model_data['feature_names']
        logger.info(f"Model loaded successfully with {len(self.feature_names)} features")

    def _extract_features_vector(self, features: Dict[str, Any]) -> np.ndarray:
        """
        Convert features dictionary to numpy array in correct order.

        Args:
            features: Dictionary of temporal features

        Returns:
            Feature vector as numpy array
        """
        feature_vector = [
            features['messages_last_30min'],
            features['messages_last_hour'],
            features['messages_last_3hours'],
            features['avg_gap_last_5_messages_min'],
            features['time_since_last_message_min'],
        ]
        return np.array([feature_vector])

    async def stage1_temporal_classification(
        self,
        messages: List[Message]
    ) -> Dict[str, Any]:
        """
        Stage 1: Extract temporal features and use Random Forest to classify.

        Args:
            messages: List of Message objects

        Returns:
            Dict with 'should_facilitate' (bool), 'probability', 'features'
        """
        logger.info("="*60)
        logger.info("STAGE 1: Temporal Feature Classification")
        logger.info("="*60)

        # Extract features from the conversation
        extractor = TemporalFeatureExtractor(messages)
        features = extractor.extract_all_features()

        logger.info(f"Extracted features:")
        for key, value in features.items():
            if isinstance(value, float):
                logger.info(f"  {key}: {value:.2f}")
            else:
                logger.info(f"  {key}: {value}")

        # Convert to feature vector
        X = self._extract_features_vector(features)

        # Get prediction and probability
        prediction = self.rf_model.predict(X)[0]
        probabilities = self.rf_model.predict_proba(X)[0]
        facilitation_probability = probabilities[1]  # Probability of class 1

        logger.info(f"Random Forest Decision:")
        logger.info(f"  Prediction: {'FACILITATE' if prediction == 1 else 'NO FACILITATION'}")
        logger.info(f"  Confidence: {facilitation_probability:.2%}")

        return {
            'should_facilitate': bool(prediction == 1),
            'probability': float(facilitation_probability),
            'features': features
        }

    async def stage2_llm_verification(
        self,
        messages: List[Message],
        last_n: int = 10
    ) -> Dict[str, Any]:
        """
        Stage 2: Use LLM to verify if facilitation is needed (zero-shot).

        Args:
            messages: List of Message objects
            last_n: Number of recent messages to send to LLM

        Returns:
            Dict with 'needs_facilitation' (bool), 'reasoning', 'confidence'
        """
        logger.info("="*60)
        logger.info("STAGE 2: LLM Zero-Shot Verification")
        logger.info("="*60)

        # Get last N messages
        recent_messages = messages[-last_n:] if len(messages) > last_n else messages

        # Format conversation for LLM
        conversation_text = self.llm_service.format_conversation(recent_messages)

        # Call LLM service with retry logic
        result = await retry_with_exponential_backoff(
            self.llm_service.verify_facilitation_needed,
            max_retries=self.max_retries,
            conversation_text=conversation_text,
            num_messages=len(recent_messages)
        )

        logger.info(f"LLM Verification Result:")
        logger.info(f"  Needs Facilitation: {result['needs_facilitation']}")
        logger.info(f"  Reasoning: {result['reasoning']}")
        logger.info(f"  Confidence: {result.get('confidence', 0):.2%}")

        return result

    async def stage3_generate_facilitation(
        self,
        messages: List[Message],
        verification_reasoning: str,
        last_n: int = 10
    ) -> Dict[str, Any]:
        """
        Stage 3: Generate facilitation response using LLM.

        Args:
            messages: List of Message objects
            verification_reasoning: Reasoning from stage 2
            last_n: Number of recent messages to use for context

        Returns:
            Dict with 'facilitation_message' and 'approach'
        """
        logger.info("="*60)
        logger.info("STAGE 3: Generate Facilitation Response")
        logger.info("="*60)

        # Get last N messages
        recent_messages = messages[-last_n:] if len(messages) > last_n else messages

        # Format conversation for LLM
        conversation_text = self.llm_service.format_conversation(recent_messages)

        # Call LLM service with retry logic
        result = await retry_with_exponential_backoff(
            self.llm_service.generate_facilitation_message,
            max_retries=self.max_retries,
            conversation_text=conversation_text,
            verification_reasoning=verification_reasoning
        )

        logger.info(f"Generated Facilitation:")
        logger.info(f"  Approach: {result['approach']}")
        logger.info(f"  Message: {result['facilitation_message']}")

        return result

    async def run_pipeline(
        self,
        messages: List[Message],
    ) -> Dict[str, Any]:
        """
        Run the complete multi-stage facilitation pipeline.

        Args:
            messages: List of Message objects

        Returns:
            Dict with complete pipeline results and final decision
        """
        logger.info("="*70)
        logger.info("FACILITATION DECISION PIPELINE")
        logger.info("="*70)
        logger.info(f"Analyzing conversation with {len(messages)} messages...")

        pipeline_result = {
            'stage1': None,
            'stage2': None,
            'stage3': None,
            'final_decision': 'NO_FACILITATION',
            'facilitation_message': None
        }

        # STAGE 1: Temporal Classification
        stage1_result = await self.stage1_temporal_classification(messages)
        pipeline_result['stage1'] = stage1_result

        if not stage1_result['should_facilitate']:
            logger.info("="*70)
            logger.info("FINAL DECISION: NO FACILITATION NEEDED")
            logger.info("="*70)
            logger.info("Random Forest determined facilitation is not needed.")
            return pipeline_result

        # STAGE 2: LLM Verification
        stage2_result = await self.stage2_llm_verification(messages)
        pipeline_result['stage2'] = stage2_result

        if not stage2_result['needs_facilitation']:
            logger.info("="*70)
            logger.info("FINAL DECISION: NO FACILITATION NEEDED")
            logger.info("="*70)
            logger.info("LLM verification determined facilitation is not needed.")
            logger.info(f"Reasoning: {stage2_result['reasoning']}")
            pipeline_result['final_decision'] = 'NO_FACILITATION_AFTER_VERIFY'
            return pipeline_result

        # STAGE 3: Generate Facilitation
        stage3_result = await self.stage3_generate_facilitation(
            messages,
            stage2_result['reasoning']
        )
        pipeline_result['stage3'] = stage3_result
        pipeline_result['final_decision'] = 'FACILITATE'
        pipeline_result['facilitation_message'] = stage3_result['facilitation_message']

        logger.info("="*70)
        logger.info("FINAL DECISION: FACILITATION NEEDED")
        logger.info("="*70)
        logger.info(f"Facilitation Message:")
        logger.info(f"  {stage3_result['facilitation_message']}")
        logger.info("="*70)

        return pipeline_result
