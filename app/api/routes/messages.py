"""
Messages webhook endpoint.
Receives incoming messages from the chat application, stores them, and initiates facilitation.
"""

import logging
import random
from typing import Tuple, List

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db, AsyncSessionLocal
from app.models.schemas import (
    WebhookIncomingRequest,
    WebhookResponse,
    MessageResponse,
    GroupUpdateRequest,
    GroupUpdateResponse,
)
from app.services.message_service import MessageService
from app.services.facilitation_service import FacilitationService
from app.services.webhook_client import WebhookClient
from app.api.middleware.auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/messages", tags=["messages"])


async def process_facilitation_background(
    group_question_id_pairs: List[Tuple[int, str]],
) -> None:
    """
    Background task to process facilitation and send responses.

    Args:
        group_question_id_pairs: List of tuples of (group id, question id), each representing a message thread
    """
    logger.info("Starting background facilitation processing")

    try:
        # Create new database session for background task
        async with AsyncSessionLocal() as session:
            # Initialize services
            facilitation_service = FacilitationService(session)
            webhook_client = WebhookClient()

            # Process facilitation for all threads
            facilitation_responses = (
                await facilitation_service.process_webhook_messages(
                    group_question_id_pairs
                )
            )

            # Send facilitation responses if any were generated
            if facilitation_responses:
                logger.info(
                    f"Sending {len(facilitation_responses)} facilitation responses "
                    "to external API"
                )
                success = await webhook_client.send_facilitation_responses(
                    facilitation_responses
                )

                if success:
                    logger.info("Successfully sent facilitation responses")
                else:
                    logger.error("Failed to send facilitation responses")
            else:
                logger.info("No facilitation responses generated")

    except Exception as e:
        logger.error(f"Error in background facilitation processing: {e}", exc_info=True)


@router.patch(
    "/group_activity",
    response_model=GroupUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update group activity",
    description="Updates group is_active status",
)
async def update_group(
    request: GroupUpdateRequest,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """
    Update group active status.

    Args:
        request: Group update request with group_id and is_active
        session: Database session
        _api_key: Validated API key

    Returns:
        Success response with updated group information
    """
    logger.info(
        f"Updating group {request.group_id} active status to {request.is_active}"
    )

    try:
        message_service = MessageService(session)

        # Update group active status
        group = await message_service.update_group_active_status(
            external_id=request.group_id, new_status=request.is_active
        )

        if not group:
            logger.warning(f"Group {request.group_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Group with ID {request.group_id} not found",
            )

        logger.info(f"Successfully updated group {request.group_id}")

        return GroupUpdateResponse(
            status="success",
            group_id=request.group_id,
            is_active=request.is_active,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating group {request.group_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating group: {str(e)}",
        )


@router.get(
    "/logs",
    response_model=List[MessageResponse],
    status_code=status.HTTP_200_OK,
    summary="Get stored messages for a group",
    description="Retrieve stored messages for a specific group by group_id",
)
async def get_messages(
    group_id: int,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """
    Retrieve stored messages for a specific group, include all threads.

    Args:
        group_id: Group ID to retrieve messages for
        session: Database session
        _api_key: Validated API key
    Returns:
        List of stored messages for the group
    """

    logger.info(f"Fetching message logs for group: {group_id}")
    try:
        message_service = MessageService(session)
        group = await message_service.get_group_by_external_id(group_id)
        message_history = await message_service.get_conversation_history(
            group, limit=20
        )

        logger.info(f"Retrieved {len(message_history)} messages for group: {group_id}")

        return message_history

    except Exception as e:
        logger.error(
            f"Error retrieving messages for group {group_id}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving messages: {str(e)}",
        )


@router.post(
    "/save",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="Receive batch messages from chat application",
    description="Webhook endpoint that receives and stores messages. Returns 200 OK on success.",
)
async def save_messages(
    request: WebhookIncomingRequest,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """
    Receive incoming messages from chat application webhook.

    This endpoint:
    1. Stores incoming messages in the database
    2. Returns 200 OK with summary

    Args:
        request: Batch of messages from the chat application
        session: Database session
        _api_key: Validated API key (from header)

    Returns:
        Success response with count of messages and groups and question threads affected
    """
    logger.info(f"Received webhook with {len(request.payload.groups)} groups")

    try:
        # Store messages
        message_service = MessageService(session)
        messages_by_group_by_question = await message_service.store_webhook_content(
            request
        )

        logger.info("Successfully stored messages.")

        return WebhookResponse(
            status="success",
            groups_affected=len(messages_by_group_by_question),
            question_threads_affected=sum(
                len(qs) for qs in messages_by_group_by_question.values()
            ),
            messages_received=sum(
                len(msgs)
                for qs in messages_by_group_by_question.values()
                for msgs in qs.values()
            ),
        )

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing messages: {str(e)}",
        )


EXAMPLE_PAYLOAD = WebhookIncomingRequest(
    payload={
        "groups_metadata": [
            {"group_id": 2, "status": "active", "status_updated_at": None},
        ],
        "groups": [
            {
                "group_id": 2,
                "group_name": "Item 2 Chat",
                "members": [
                    {
                        "user_id": "e1000000-e5ef-4758-a0e3-e19a009b2853",
                        "first_name": "Cristina",
                        "last_name": None,
                    },
                    {
                        "user_id": "50000000-780a-473c-91fc-b0043688eefc",
                        "first_name": "Michelle",
                        "last_name": None,
                    },
                ],
                "threads": [
                    {
                        "question": {
                            "id": "f0000000-3e89-481e-b3f6-7082fdae2af5",
                            "text": "Do your feelings of responsibility to others help you through your darkest struggles or add to your burdens? How so?",
                            "options": ["Helps me . . .", "Burdens me . . .", "Actually . . ."],
                            "status": "active",
                            "unlock_order": 3,
                        },
                        "messages": [
                            {
                                "user_id": "e1000000-e5ef-4758-a0e3-e19a009b2853",
                                "first_name": "Cristina",
                                "last_name": None,
                                "content": "<highlight>Burdens me . . .</highlight> I feel nothing but pressure when it comes to this type of responsability",
                                "created_at": "2026-02-16 08:56:44.292422+00:00",
                                "is_ai": False,
                                "is_current_member": True,
                            },
                            {
                                "user_id": "60000000-0983-42e0-ab2b-bbcd15d0cc2b",
                                "first_name": None,
                                "last_name": None,
                                "content": "<highlight>Helps me . . .</highlight> It's cool to know you can influence people into making good decisions",
                                "created_at": "2026-02-16 09:02:26.287041+00:00",
                                "is_ai": False,
                                "is_current_member": False,
                            },
                            {
                                "user_id": "50000000-780a-473c-91fc-b0043688eefc",
                                "first_name": "Michelle",
                                "last_name": None,
                                "content": "<highlight>Actually . . .</highlight> Not really sure",
                                "created_at": "2026-02-16 09:26:54.603603+00:00",
                                "is_ai": False,
                                "is_current_member": True,
                            },
                        ],
                        "last_ai_message_at": None,
                    }
                ],
            }
        ],
    }
)


@router.post(
    "/trigger",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="Manually trigger facilitation pipeline",
    description="Development endpoint to manually trigger the full webhook + facilitation pipeline. Defaults to an example payload if none is provided.",
)
async def trigger_facilitation(
    background_tasks: BackgroundTasks,
    request: WebhookIncomingRequest = Body(default=EXAMPLE_PAYLOAD),
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """
    Manually trigger the facilitation pipeline for testing.

    Accepts the same payload as /webhook. If no body is sent, uses the built-in
    example payload so you can test without constructing data by hand.
    """
    return await receive_messages_webhook(request, background_tasks, session, _api_key)


@router.post(
    "/webhook",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="Receive batch messages from chat application",
    description="Webhook endpoint that receives and stores messages, then triggers facilitation in background. Returns 200 OK immediately.",
)
async def receive_messages_webhook(
    request: WebhookIncomingRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """
    Receive incoming messages from chat application webhook.

    This endpoint:
    1. Stores incoming messages in the database
    2. Triggers facilitation processing in background
    3. Returns 200 OK immediately with summary

    Background task will:
    - Run facilitation pipeline for each thread
    - Send facilitation responses to external API if needed

    Args:
        request: Batch of messages from the chat application
        background_tasks: FastAPI background tasks
        session: Database session
        _api_key: Validated API key (from header)

    Returns:
        Success response with count of messages and groups and question threads affected
    """
    logger.info(f"Received webhook with {len(request.payload.groups)} groups")

    try:
        # Store messages and sync state
        message_service = MessageService(session)
        messages_by_group_by_question = await message_service.store_webhook_content(
            request
        )

        logger.info("Successfully stored messages.")

        # Collect active threads from this payload
        payload_active_pairs = {
            (group.group_id, thread.question.id)
            for group in request.payload.groups
            for thread in group.threads
            if thread.question.status == "active"
        }

        # Also include active threads from DB not in the payload, with 20% probability
        other_active_pairs = await message_service.get_active_group_questions_not_in(
            payload_active_pairs
        )
        sampled_pairs = [p for p in other_active_pairs if random.random() < 0.2]

        all_pairs = list(payload_active_pairs) + sampled_pairs
        logger.info(
            f"Facilitation targets: {len(payload_active_pairs)} from payload, "
            f"{len(sampled_pairs)} sampled from {len(other_active_pairs)} other active threads"
        )

        # Add background task to process facilitation
        background_tasks.add_task(process_facilitation_background, all_pairs)
        logger.info("Added facilitation processing to background tasks")

        # Return immediately with success
        return WebhookResponse(
            status="success",
            groups_affected=len(messages_by_group_by_question),
            question_threads_affected=sum(
                len(qs) for qs in messages_by_group_by_question.values()
            ),
            messages_received=sum(
                len(msgs)
                for qs in messages_by_group_by_question.values()
                for msgs in qs.values()
            ),
        )

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing messages: {str(e)}",
        )
