"""
Facilitation endpoints.
Provides endpoints for manual facilitation checks and viewing logs.
"""

import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.schemas import FacilitationLogResponse
from app.services.message_service import MessageService
from app.services.facilitation_service import FacilitationService
from app.api.middleware.auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/facilitation", tags=["facilitation"])


@router.get(
    "/logs",
    response_model=List[FacilitationLogResponse],
    status_code=status.HTTP_200_OK,
    summary="Get facilitation logs",
    description="Retrieve facilitation decision logs for a specific chatroom",
)
async def get_facilitation_logs(
    group_id: str = Query(..., description="Chatroom UUID to get logs for"),
    limit: int = Query(
        10, ge=1, le=100, description="Maximum number of logs to return"
    ),
    session: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    """
    Get facilitation logs for a specific chatroom.

    Args:
        group_id: External chatroom ID
        limit: Maximum number of logs to return (1-100)
        session: Database session
        _api_key: Validated API key

    Returns:
        List of facilitation logs
    """
    logger.info(f"Fetching facilitation logs for group: {group_id}, limit: {limit}")

    try:
        # Get chatroom
        message_service = MessageService(session)
        chatroom = await message_service.get_chatroom_by_external_id(group_id)

        if not chatroom:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chatroom not found: {group_id}",
            )

        # Get logs
        facilitation_service = FacilitationService(session)
        logs = await facilitation_service.get_chatroom_facilitation_logs(
            chatroom, limit=limit
        )

        # Convert to response models
        from app.models.database import FacilitationDecision

        return [
            FacilitationLogResponse(
                id=log["id"],
                chatroom_id=chatroom.id,
                triggered_at=datetime.fromisoformat(log["triggered_at"]),
                final_decision=FacilitationDecision(log["final_decision"]),
                facilitation_message=log["facilitation_message"],
                message_sent_at=datetime.fromisoformat(log["message_sent_at"])
                if log["message_sent_at"]
                else None,
                stage1_result=log["stage1_result"],
                stage2_result=log["stage2_result"],
                stage3_result=log["stage3_result"],
            )
            for log in logs
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching facilitation logs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching logs: {str(e)}",
        )
