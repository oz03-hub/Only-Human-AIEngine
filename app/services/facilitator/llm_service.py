"""
OpenAI LLM service wrapper for facilitation stages.
Handles all interactions with the OpenAI API.
"""

import json
import logging
from typing import Dict, Any, Optional, List

from openai import AsyncOpenAI

from .prompts import (
    STAGE_2_SYSTEM_PROMPT,
    STAGE_2_USER_PROMPT,
    STAGE_3_SYSTEM_PROMPT,
    STAGE_3_USER_PROMPT,
    STAGE_3_RED_FLAG_FEEDBACK,
    STAGE_4_SYSTEM_PROMPT,
    STAGE_4_USER_PROMPT,
)

from app.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """Service for interacting with OpenAI LLM API."""

    def __init__(self):
        """
        Initialize LLM service.

        Args:
            api_key: OpenAI API key (uses settings if not provided)
            model: Model name (uses settings if not provided)
        """
        self.api_key = settings.openai_api_key
        self.stage_2_model = settings.stage_2_model
        self.stage_3_model = settings.stage_3_model
        self.stage_4_model = settings.stage_4_model
        self.client = AsyncOpenAI(api_key=self.api_key)
        logger.debug(f"LLM service initialized with models: stage2={self.stage_2_model}, stage3={self.stage_3_model}, stage4={self.stage_4_model}")

    async def verify_facilitation_needed(
        self,
        topic: str,
        conversation_text: str,
        num_messages: int,
        current_time: str = "",
    ) -> Dict[str, Any]:
        """
        Stage 2: Use LLM to verify if facilitation is needed.

        Args:
            topic: String group question
            conversation_text: Formatted conversation history
            num_messages: Number of messages in the conversation
            current_time: Current simulated time as HH:MM string

        Returns:
            Dict with 'needs_facilitation' (bool), 'reasoning', 'confidence'
        """
        logger.info(
            f"Stage 2: Verifying facilitation need for conversation with {num_messages} messages"
        )

        # Format the user prompt with dynamic context
        user_prompt = STAGE_2_USER_PROMPT.format(
            len_recent_message=num_messages,
            conversation_text=conversation_text,
            group_question=topic,
            current_time=current_time,
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.stage_2_model,
                messages=[
                    {"role": "system", "content": STAGE_2_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
            logger.info(
                f"Stage 2 result: needs_facilitation={result['needs_facilitation']}."
            )

            return result

        except Exception as e:
            logger.error(f"Error calling OpenAI API for stage 2: {e}", exc_info=True)
            return {
                "needs_facilitation": False,
                "reasoning": f"Error during verification: {str(e)}",
            }

    async def generate_facilitation_message(
        self,
        topic: str,
        conversation_text: str,
        verification_reasoning: str,
        intervention_focus: str = "general",
        current_time: str = "",
        red_flag_feedback: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Stage 3: Generate facilitation message using LLM.

        Args:
            topic: String group question
            conversation_text: Formatted conversation history
            verification_reasoning: Reasoning from stage 2
            intervention_focus: Focus area for intervention from stage 2
            current_time: Current simulated time as HH:MM string

        Returns:
            Dict with 'facilitation_message' and 'approach'
        """
        logger.info("Stage 3: Generating facilitation message")

        # Format the user prompt with dynamic context
        user_prompt = STAGE_3_USER_PROMPT.format(
            group_question=topic,
            verification_reasoning=verification_reasoning,
            conversation_text=conversation_text,
            intervention_focus=intervention_focus,
            current_time=current_time,
        )

        if red_flag_feedback:
            user_prompt += STAGE_3_RED_FLAG_FEEDBACK.format(
                red_flags=", ".join(red_flag_feedback.get("red_flags_detected", []))
                or "unspecified",
                reasoning=red_flag_feedback.get("reasoning", ""),
            )

        try:
            response = await self.client.chat.completions.create(
                model=self.stage_3_model,
                messages=[
                    {"role": "system", "content": STAGE_3_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.8,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
            logger.info(f"Stage 3 result: approach={result.get('approach', 'N/A')}")

            return result

        except Exception as e:
            logger.error(f"Error calling OpenAI API for stage 3: {e}", exc_info=True)
            return {
                "facilitation_message": "How is everyone doing?",
                "approach": f"Error - fallback message (error: {str(e)})",
            }

    async def verify_red_flags(
        self,
        topic: str,
        conversation_text: str,
        facilitation_message: str,
    ) -> Dict[str, Any]:
        """
        Stage 4: Verify that generated facilitation message doesn't contain red flags.

        Args:
            topic: String group question
            conversation_text: Formatted conversation history
            facilitation_message: The facilitation message to check

        Returns:
            Dict with 'has_red_flags', 'red_flags_detected', 'severity', 'reasoning', 'recommendation'
        """
        logger.info("Stage 4: Verifying red flags in facilitation message")

        # Format the user prompt with dynamic context
        user_prompt = STAGE_4_USER_PROMPT.format(
            group_question=topic,
            conversation_text=conversation_text,
            facilitation_message=facilitation_message,
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.stage_4_model,
                messages=[
                    {"role": "system", "content": STAGE_4_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
            logger.info(
                f"Stage 4 result: has_red_flags={result['has_red_flags']}, "
                f"recommendation={result['recommendation']}"
            )

            return result

        except Exception as e:
            logger.error(f"Error calling OpenAI API for stage 4: {e}", exc_info=True)
            return {
                "has_red_flags": False,
                "red_flags_detected": [],
                "severity": "none",
                "reasoning": f"Error during red flag verification: {str(e)}",
                "recommendation": "approve",  # Default to approve on error to avoid blocking
            }

    def format_conversation(
        self, messages: List[Dict[str, Any]], last_n: Optional[int] = None
    ) -> str:
        """
        Format messages into a conversation string for LLM.

        Args:
            messages: List of Message objects (with user relationship loaded)
            last_n: Number of recent messages to include (None = all)

        Returns:
            Formatted conversation string
        """
        if last_n:
            messages = messages[-last_n:]

        conversation_lines = []
        for msg in messages:
            if hasattr(msg, "timestamp"):
                time_str = msg.timestamp.strftime("%H:%M")
                sender_name = msg.user.first_name
                sender_id = msg.user_id
                content = msg.content
            else:
                timestamp = msg.get("timestamp") or msg.get("time")
                time_str = timestamp if timestamp else "Unknown"
                sender_id = msg.get("sender_id", "0000")
                sender_name = msg.get("sender_name", msg.get("sender", "Unknown"))
                content = msg.get("content", "")

            conversation_lines.append(
                f"[{time_str}] ({sender_id}) {sender_name}: {content}"
            )

        return "\n".join(conversation_lines)
