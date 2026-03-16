"""
Tests for the webhook client.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.services.webhook_client import WebhookClient


class TestWebhookClient:
    """Test the webhook client."""

    @pytest.fixture
    def webhook_client(self):
        """Create webhook client with test URL."""
        return WebhookClient(
            webhook_url="https://test-api.com/facilitation", timeout=10.0, max_retries=3
        )

    @pytest.fixture
    def sample_responses(self):
        """Sample facilitation responses."""
        return [
            {"group_id": 123, "question_id": "q1", "message": "How is everyone doing?"},
            {"group_id": 456, "question_id": "q2", "message": "Great discussion!"},
        ]

    @pytest.mark.asyncio
    async def test_send_facilitation_responses_success(
        self, webhook_client, sample_responses
    ):
        """Test successful sending of facilitation responses."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()

            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()

            mock_client_class.return_value = mock_client

            result = await webhook_client.send_facilitation_responses(sample_responses)

            assert result is True
            mock_client.post.assert_called_once()

            # Verify payload structure
            call_args = mock_client.post.call_args
            assert call_args[0][0] == "https://test-api.com/facilitation/api/ai/facilitation"
            payload = call_args[1]["json"]
            assert "facilitation_responses" in payload
            assert len(payload["facilitation_responses"]) == 2

    @pytest.mark.asyncio
    async def test_send_empty_responses(self, webhook_client):
        """Test sending empty responses list."""
        result = await webhook_client.send_facilitation_responses([])

        # Should return True without making any requests
        assert result is True

    @pytest.mark.asyncio
    async def test_send_no_webhook_url_configured(self, sample_responses):
        """Test behavior when webhook URL is not configured."""
        client = WebhookClient(webhook_url="", max_retries=3)

        result = await client.send_facilitation_responses(sample_responses)

        # Should return False when URL not configured
        assert result is False

    @pytest.mark.asyncio
    async def test_send_retry_on_server_error(self, webhook_client, sample_responses):
        """Test retry logic on server errors (5xx)."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = MagicMock()

            # First two calls fail with 500, third succeeds
            fail_response = MagicMock()
            fail_response.status_code = 500
            fail_response.raise_for_status = MagicMock(
                side_effect=httpx.HTTPStatusError(
                    "Server Error", request=MagicMock(), response=fail_response
                )
            )

            success_response = MagicMock()
            success_response.status_code = 200
            success_response.raise_for_status = MagicMock()

            mock_client.post = AsyncMock(
                side_effect=[fail_response, fail_response, success_response]
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()

            mock_client_class.return_value = mock_client

            # Use short delays for testing
            webhook_client.max_retries = 2

            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await webhook_client.send_facilitation_responses(
                    sample_responses
                )

            assert result is True
            assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_send_no_retry_on_client_error(
        self, webhook_client, sample_responses
    ):
        """Test that client errors (4xx) are not retried."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = MagicMock()

            fail_response = MagicMock()
            fail_response.status_code = 400
            fail_response.raise_for_status = MagicMock(
                side_effect=httpx.HTTPStatusError(
                    "Bad Request", request=MagicMock(), response=fail_response
                )
            )

            mock_client.post = AsyncMock(return_value=fail_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()

            mock_client_class.return_value = mock_client

            result = await webhook_client.send_facilitation_responses(sample_responses)

            # Should fail immediately without retries
            assert result is False
            assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_send_max_retries_exceeded(self, webhook_client, sample_responses):
        """Test behavior when max retries is exceeded."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = MagicMock()

            fail_response = MagicMock()
            fail_response.status_code = 503
            fail_response.raise_for_status = MagicMock(
                side_effect=httpx.HTTPStatusError(
                    "Service Unavailable", request=MagicMock(), response=fail_response
                )
            )

            mock_client.post = AsyncMock(return_value=fail_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()

            mock_client_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await webhook_client.send_facilitation_responses(
                    sample_responses
                )

            # Should fail after all retries
            assert result is False
            assert mock_client.post.call_count == 4  # Initial + 3 retries

    @pytest.mark.asyncio
    async def test_send_network_error_retry(self, webhook_client, sample_responses):
        """Test retry on network errors."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = MagicMock()

            # Simulate network errors then success
            success_response = MagicMock()
            success_response.status_code = 200
            success_response.raise_for_status = MagicMock()

            mock_client.post = AsyncMock(
                side_effect=[
                    httpx.RequestError("Network error"),
                    httpx.TimeoutException("Timeout"),
                    success_response,
                ]
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()

            mock_client_class.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await webhook_client.send_facilitation_responses(
                    sample_responses
                )

            assert result is True
            assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_send_validates_response_schema(self, webhook_client):
        """Test that responses are validated before sending."""
        # Invalid response missing required field
        invalid_responses = [
            {
                "group_id": 123,
                # Missing "question_id"
                "message": "Test",
            }
        ]

        with pytest.raises(Exception):  # Pydantic validation error
            await webhook_client.send_facilitation_responses(invalid_responses)

    @pytest.mark.asyncio
    async def test_send_includes_correct_headers(
        self, webhook_client, sample_responses
    ):
        """Test that correct headers are included in request."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()

            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()

            mock_client_class.return_value = mock_client

            await webhook_client.send_facilitation_responses(sample_responses)

            # Verify headers
            call_args = mock_client.post.call_args
            headers = call_args[1]["headers"]
            assert headers["Content-Type"] == "application/json"
