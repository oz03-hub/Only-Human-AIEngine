"""
OpenAI LLM service wrapper for facilitation stages.
Handles all interactions with the OpenAI API.
"""

import json
import logging
from typing import Dict, Any, Optional

from openai import OpenAI, AsyncOpenAI
from openai.types.chat import ChatCompletion

from app.config import settings
from app.core.prompts import STAGE_2_PROMPT, STAGE_3_PROMPT

logger = logging.getLogger(__name__)


class LLMService:
    """Service for interacting with OpenAI LLM API."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize LLM service.

        Args:
            api_key: OpenAI API key (uses settings if not provided)
            model: Model name (uses settings if not provided)
        """
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.llm_model
        self.client = AsyncOpenAI(api_key=self.api_key)
        logger.info(f"LLM service initialized with model: {self.model}")

    async def verify_facilitation_needed(
        self,
        conversation_text: str,
        num_messages: int
    ) -> Dict[str, Any]:
        """
        Stage 2: Use LLM to verify if facilitation is needed.

        Args:
            conversation_text: Formatted conversation history
            num_messages: Number of messages in the conversation

        Returns:
            Dict with 'needs_facilitation' (bool), 'reasoning', 'confidence'
        """
        logger.info(f"Stage 2: Verifying facilitation need for conversation with {num_messages} messages")

        # Format the prompt with the conversation
        prompt = STAGE_2_PROMPT.format(
            len_recent_message=num_messages,
            conversation_text=conversation_text
        )

        try:
            response: ChatCompletion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert online support group facilitator. Respond only with valid JSON."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
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
        conversation_text: str,
        verification_reasoning: str
    ) -> Dict[str, Any]:
        """
        Stage 3: Generate facilitation message using LLM.

        Args:
            conversation_text: Formatted conversation history
            verification_reasoning: Reasoning from stage 2

        Returns:
            Dict with 'facilitation_message' and 'approach'
        """
        logger.info("Stage 3: Generating facilitation message")

        # Format the prompt
        prompt = STAGE_3_PROMPT.format(
            verification_reasoning=verification_reasoning,
            conversation_text=conversation_text
        )

        try:
            response: ChatCompletion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert online support group facilitator specializing in caregiver support. Respond only with valid JSON."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            logger.info(f"Stage 3 result: approach={result.get('approach', 'N/A')}")

            return result

        except Exception as e:
            logger.error(f"Error calling OpenAI API for stage 3: {e}", exc_info=True)
            return {
                "facilitation_message": "How is everyone doing?",
                "approach": f"Error - fallback message (error: {str(e)})"
            }

    def format_conversation(self, messages: list, last_n: Optional[int] = None) -> str:
        """
        Format messages into a conversation string for LLM.

        Args:
            messages: List of message objects with sender_name, timestamp, content
            last_n: Number of recent messages to include (None = all)

        Returns:
            Formatted conversation string
        """
        if last_n:
            messages = messages[-last_n:]

        conversation_lines = []
        for msg in messages:
            # Handle both database objects and dicts
            if hasattr(msg, 'timestamp'):
                time_str = msg.timestamp.strftime('%H:%M')
                sender_name = msg.sender_name
                sender_id = msg.sender_id
                content = msg.content
            else:
                timestamp = msg.get('timestamp') or msg.get('time')
                time_str = timestamp.strftime('%H:%M') if timestamp else 'Unknown'
                sender_id = msg.get('sender_id', '0000')
                sender_name = msg.get('sender_name', msg.get('sender', 'Unknown'))
                content = msg.get('content', '')

            conversation_lines.append(f"[{time_str}] ({sender_id}) {sender_name}: {content}")

        return "\n".join(conversation_lines)
