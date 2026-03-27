"""
Webhook client service for sending facilitation responses to external API.
Handles HTTP requests with retry logic and error handling.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional

import httpx

from app.config import settings
from app.models.schemas import (
    FacilitationMessageResponse,
    FacilitationBatchMessagesResponse,
)

logger = logging.getLogger(__name__)


class WebhookClient:
    """Client for sending facilitation responses to external application API."""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        """
        Initialize webhook client.

        Args:
            webhook_url: External API webhook URL (uses settings if not provided)
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
        """
        base_url = (webhook_url or settings.application_webhook_url).rstrip("/")
        self.webhook_url = f"{base_url}/api/ai/facilitation"
        self.timeout = timeout
        self.max_retries = max_retries
        logger.info(f"Webhook client initialized. Target URL: {self.webhook_url}")

    async def send_facilitation_responses(
        self, responses: List[Dict[str, Any]]
    ) -> bool:
        """
        Send facilitation responses to external API.

        Args:
            responses: List of dicts with 'group_id', 'question_id', 'message'

        Returns:
            True if successful, False otherwise
        """
        if not responses:
            logger.info("No facilitation responses to send")
            return True

        if not self.webhook_url:
            logger.error(
                "APPLICATION_WEBHOOK_URL not configured. Cannot send responses."
            )
            return False

        # Convert to Pydantic models for validation
        facilitation_messages = [
            FacilitationMessageResponse(
                group_id=resp["group_id"],
                question_id=resp["question_id"],
                content=resp["message"],
            )
            for resp in responses
        ]

        # Create batch response
        batch_response = FacilitationBatchMessagesResponse(
            facilitation_responses=facilitation_messages
        )

        logger.info(
            f"Sending {len(facilitation_messages)} facilitation messages to "
            f"{self.webhook_url}"
        )

        # Send with retry logic
        return await self._send_with_retry(batch_response.model_dump())

    async def _send_with_retry(
        self,
        payload: Dict[str, Any],
        initial_delay: float = 1.0,
        max_delay: float = 10.0,
        exponential_base: float = 2.0,
    ) -> bool:
        """
        Send HTTP POST request with exponential backoff retry.

        Args:
            payload: JSON payload to send
            initial_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds
            exponential_base: Base for exponential backoff

        Returns:
            True if successful, False otherwise
        """
        last_exception = None

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.post(
                        self.webhook_url,
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {settings.api_key}",
                        },
                    )

                    # Check if request was successful
                    response.raise_for_status()

                    logger.info(
                        f"Successfully sent facilitation responses. "
                        f"Status: {response.status_code}"
                    )
                    return True

                except httpx.HTTPStatusError as e:
                    last_exception = e
                    logger.error(
                        f"HTTP error {e.response.status_code} on attempt "
                        f"{attempt + 1}/{self.max_retries + 1}: {e}"
                    )

                    # Don't retry on client errors (4xx)
                    if 400 <= e.response.status_code < 500:
                        logger.error(
                            f"Client error ({e.response.status_code}). Not retrying."
                        )
                        return False

                except (httpx.RequestError, httpx.TimeoutException) as e:
                    last_exception = e
                    logger.warning(
                        f"Request error on attempt {attempt + 1}/{self.max_retries + 1}: {e}"
                    )

                except Exception as e:
                    last_exception = e
                    logger.error(
                        f"Unexpected error on attempt {attempt + 1}/{self.max_retries + 1}: {e}",
                        exc_info=True,
                    )

                # If this was the last attempt, give up
                if attempt == self.max_retries:
                    logger.error(
                        f"Failed to send facilitation responses after "
                        f"{self.max_retries + 1} attempts. Last error: {last_exception}"
                    )
                    return False

                # Calculate delay with exponential backoff
                delay = min(initial_delay * (exponential_base**attempt), max_delay)

                logger.info(f"Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)

        return False
