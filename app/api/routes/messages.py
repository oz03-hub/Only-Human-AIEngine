"""
Messages webhook endpoint.
Receives incoming messages from the chat application, stores them, and initiates facilitation.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.schemas import WebhookIncomingRequest, WebhookIncomingGroup, WebhookIncomingMessage, WebhookResponse, MessageBase
from app.services.message_service import MessageService
from app.api.middleware.auth import verify_api_key
from typing import List

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/messages", tags=["messages"])


@router.get(
    "/logs",
    response_model=List[MessageBase],
    status_code=status.HTTP_200_OK,
    summary="Get stored messages for a chatroom",
    description="Retrieve stored messages for a specific chatroom by group_id",
)
async def get_messages(
    group_id: str,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """
    Retrieve stored messages for a specific chatroom.

    Args:
        group_id: Chatroom UUID to retrieve messages for
        session: Database session
        _api_key: Validated API key
    Returns:
        List of stored messages for the chatroom
    """

    logger.info(f"Fetching message logs for group: {group_id}")
    try:
        message_service = MessageService(session)
        chatroom = await message_service.get_chatroom_by_external_id(group_id)
        messages = await message_service.get_conversation_history(chatroom, 10)

        logger.info(f"Retrieved {len(messages)} messages for group: {group_id}")

        return messages

    except Exception as e:
        logger.error(
            f"Error retrieving messages for group {group_id}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving messages: {str(e)}",
        )


@router.post(
    "/webhook",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="Receive batch messages from chat application",
    description="Webhook endpoint that receives and stores messages. Returns 200 OK on success. After saving messages it starts facilitation process.",
)
async def receive_messages_webhook(
    request: WebhookIncomingRequest,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """
    Receive incoming messages from chat application webhook.

    This endpoint:
    1. Stores incoming messages in the database
    2. Returns 200 OK with summary
    3. Starts facilitation processing

    Args:
        request: Batch of messages from the chat application
        session: Database session
        _api_key: Validated API key (from header)

    Returns:
        Success response with count of messages and chatrooms affected
    """
    logger.info(f"Received webhook with {len(request.messages)} messages")

    try:
        # Store messages
        message_service = MessageService(session)
        messages_by_group = await message_service.store_webhook_messages(
            request.messages
        )

        logger.info(
            f"Successfully stored messages for {len(messages_by_group)} chatrooms"
        )

        return WebhookResponse(
            status="success",
            messages_received=len(request.messages),
            chatrooms_affected=len(messages_by_group),
        )

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing messages: {str(e)}",
        )
