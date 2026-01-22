"""
Facilitation service for orchestrating the decision pipeline.
Coordinates between the pipeline, message service, and database.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pipeline import FacilitationDecisionPipeline
from app.services.message_service import MessageService
from app.services.llm_service import LLMService
from app.models.database import Chatroom, FacilitationDecision

logger = logging.getLogger(__name__)


class FacilitationService:
    """Service for running facilitation checks and logging results."""

    def __init__(self, session: AsyncSession):
        """
        Initialize facilitation service.

        Args:
            session: Database session
        """
        self.session = session
        self.message_service = MessageService(session)
        self.llm_service = LLMService()
        self.pipeline = FacilitationDecisionPipeline(llm_service=self.llm_service)

    async def check_and_facilitate(
        self,
        chatroom: Chatroom,
        min_messages: int = 5
    ) -> Dict[str, Any]:
        """
        Run facilitation check for a chatroom.

        Args:
            chatroom: Chatroom object to check
            min_messages: Minimum number of messages required to run pipeline

        Returns:
            Dict with facilitation decision and message (if applicable)
        """
        logger.info(f"Running facilitation check for chatroom: {chatroom.external_id}")

        # Get conversation history
        messages = await self.message_service.get_conversation_history(chatroom)

        if len(messages) < min_messages:
            logger.info(f"Not enough messages ({len(messages)}/{min_messages}). Skipping facilitation check.")
            return {
                'decision': 'NO_FACILITATION',
                'message': None,
                'reason': f'Insufficient messages ({len(messages)}/{min_messages})',
                'log_id': None
            }

        # Run the pipeline
        try:
            pipeline_result = await self.pipeline.run_pipeline(messages)

            # Determine final decision
            final_decision = pipeline_result['final_decision']
            facilitation_message = pipeline_result.get('facilitation_message')
            message_sent_at = datetime.now() if facilitation_message else None

            # Create facilitation log
            log = await self.message_service.create_facilitation_log(
                chatroom=chatroom,
                stage1_result=pipeline_result.get('stage1'),
                stage2_result=pipeline_result.get('stage2'),
                stage3_result=pipeline_result.get('stage3'),
                final_decision=final_decision,
                facilitation_message=facilitation_message,
                message_sent_at=message_sent_at
            )

            await self.session.commit()

            logger.info(
                f"Facilitation check completed for {chatroom.external_id}. "
                f"Decision: {final_decision}, Log ID: {log.id}"
            )

            return {
                'decision': final_decision,
                'message': facilitation_message,
                'log_id': log.id,
                'pipeline_result': pipeline_result
            }

        except Exception as e:
            logger.error(f"Error during facilitation check: {e}", exc_info=True)
            await self.session.rollback()
            raise

    async def process_webhook_messages(
        self,
        messages_by_group: Dict[str, List]
    ) -> List[Dict[str, Any]]:
        """
        Process webhook messages and run facilitation checks for affected chatrooms.

        Args:
            messages_by_group: Dict mapping group_id to list of Message objects

        Returns:
            List of facilitation responses for chatrooms that need facilitation
        """
        facilitation_responses = []

        for group_id, messages in messages_by_group.items():
            logger.info(f"Processing {len(messages)} new messages for group {group_id}")

            # Get chatroom
            chatroom = await self.message_service.get_chatroom_by_external_id(group_id)
            if not chatroom:
                logger.warning(f"Chatroom not found for group_id: {group_id}")
                continue

            # Run facilitation check
            result = await self.check_and_facilitate(chatroom)

            # Add to responses if facilitation is needed
            if result['message']:
                facilitation_responses.append({
                    'group_id': group_id,
                    'message': result['message']
                })

        logger.info(f"Generated {len(facilitation_responses)} facilitation messages")
        return facilitation_responses

    async def get_chatroom_facilitation_logs(
        self,
        chatroom: Chatroom,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get recent facilitation logs for a chatroom.

        Args:
            chatroom: Chatroom object
            limit: Maximum number of logs to retrieve

        Returns:
            List of facilitation log dicts
        """
        from sqlalchemy import select, desc
        from app.models.database import FacilitationLog

        result = await self.session.execute(
            select(FacilitationLog)
            .where(FacilitationLog.chatroom_id == chatroom.id)
            .order_by(desc(FacilitationLog.triggered_at))
            .limit(limit)
        )
        logs = result.scalars().all()

        return [
            {
                'id': log.id,
                'triggered_at': log.triggered_at.isoformat(),
                'final_decision': log.final_decision.value,
                'facilitation_message': log.facilitation_message,
                'message_sent_at': log.message_sent_at.isoformat() if log.message_sent_at else None,
                'stage1_result': log.stage1_result,
                'stage2_result': log.stage2_result,
                'stage3_result': log.stage3_result
            }
            for log in logs
        ]
