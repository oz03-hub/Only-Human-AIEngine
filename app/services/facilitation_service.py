"""
Facilitation service for orchestrating the decision pipeline.
Coordinates between the pipeline, message service, and database.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.pipeline import FacilitationDecisionPipeline
from app.services.message_service import MessageService
from app.services.llm_service import LLMService
from app.models.database import Group, GroupQuestion, FacilitationDecision
from app.config import settings

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
        group: Group,
        group_question: GroupQuestion,
        min_messages: int = 5,
        limit_messages: int = 10,
    ) -> Dict[str, Any]:
        """
        Run facilitation check for a specific thread (group + question).

        Args:
            group: Group object to check
            group_question: GroupQuestion object representing the thread
            min_messages: Minimum number of messages required to run pipeline
            limit_messages: Number of messages retrieved from thread

        Returns:
            Dict with facilitation decision and message (if applicable)
        """
        logger.info(
            f"Running facilitation check for group {group.external_id}, "
            f"thread {group_question.id}"
        )

        # Get conversation history for this specific thread
        messages = await self.message_service.get_conversation_history(
            group=group, group_question=group_question, limit=limit_messages
        )

        if len(messages) < min_messages:
            logger.info(
                f"Not enough messages ({len(messages)}/{min_messages}). "
                "Skipping facilitation check."
            )
            return {
                "decision": "NO_FACILITATION",
                "message": None,
                "reason": f"Insufficient messages ({len(messages)}/{min_messages})",
                "log_id": None,
            }

        # Run the pipeline
        try:
            pipeline_result = await self.pipeline.run_pipeline(messages)

            # Determine final decision
            final_decision = pipeline_result["final_decision"]
            facilitation_message = pipeline_result.get("facilitation_message")
            message_sent_at = datetime.now() if facilitation_message else None

            # Create facilitation log
            log = await self.message_service.create_facilitation_log(
                group=group,
                group_question=group_question,
                stage1_result=pipeline_result.get("stage1"),
                stage2_result=pipeline_result.get("stage2"),
                stage3_result=pipeline_result.get("stage3"),
                final_decision=final_decision,
                facilitation_message=facilitation_message,
                message_sent_at=message_sent_at,
            )

            await self.session.commit()

            logger.info(
                f"Facilitation check completed for group {group.external_id}, "
                f"thread {group_question.id}. Decision: {final_decision}, Log ID: {log.id}"
            )

            return {
                "decision": final_decision,
                "message": facilitation_message,
                "log_id": log.id,
                "pipeline_result": pipeline_result,
            }

        except Exception as e:
            logger.error(f"Error during facilitation check: {e}", exc_info=True)
            await self.session.rollback()
            raise

    async def process_webhook_messages(
        self, group_question_id_pairs: List[Tuple[int, str]]
    ) -> List[Dict[str, Any]]:
        """
        Process webhook messages and run facilitation checks for affected threads.

        Args:
            group_question_id_pairs: List of tuple of (group id, question id), each representing a thread

        Returns:
            List of facilitation responses with group_id, question_id, and message
        """
        facilitation_responses = []

        for group_external_id, question_external_id in group_question_id_pairs:
            logger.info(
                f"Processing group {group_external_id} with {question_external_id} question id thread"
            )

            # Get group
            group = await self.message_service.get_group_by_external_id(
                group_external_id
            )
            if not group:
                logger.warning(f"Group not found for group_id: {group_external_id}")
                continue

            # Get the Question and GroupQuestion objects
            question = await self.message_service.get_question_by_external_id(
                question_external_id
            )
            if not question:
                logger.warning(
                    f"Question not found for question_id: {question_external_id}"
                )
                continue

            # Get GroupQuestion (thread)
            result = await self.session.execute(
                select(GroupQuestion).where(
                    and_(
                        GroupQuestion.group_id == group.id,
                        GroupQuestion.question_id == question.id,
                    )
                )
            )
            group_question = result.scalar_one_or_none()

            if not group_question:
                logger.warning(
                    f"GroupQuestion not found for group {group_external_id}, "
                    f"question {question_external_id}"
                )
                continue

            # Run facilitation check for this thread
            result = await self.check_and_facilitate(
                group,
                group_question,
                min_messages=settings.min_messages,
                limit_messages=settings.limit_messages,
            )

            # Add to responses if facilitation is needed
            if result["message"]:
                facilitation_responses.append(
                    {
                        "group_id": group_external_id,
                        "question_id": question_external_id,
                        "message": result["message"],
                    }
                )

        logger.info(f"Generated {len(facilitation_responses)} facilitation messages")
        return facilitation_responses

    async def get_thread_facilitation_logs(
        self,
        group: Group,
        group_question: Optional[GroupQuestion] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get recent facilitation logs for a group or specific thread.

        Args:
            group: Group object
            group_question: Optional GroupQuestion to filter by specific thread
            limit: Maximum number of logs to retrieve

        Returns:
            List of facilitation log dicts
        """
        from sqlalchemy import select, desc, and_
        from app.models.database import FacilitationLog

        conditions = [FacilitationLog.group_id == group.id]

        if group_question:
            conditions.append(FacilitationLog.group_question_id == group_question.id)

        result = await self.session.execute(
            select(FacilitationLog)
            .where(and_(*conditions))
            .order_by(desc(FacilitationLog.triggered_at))
            .limit(limit)
        )
        logs = result.scalars().all()

        return [
            {
                "id": log.id,
                "triggered_at": log.triggered_at.isoformat(),
                "final_decision": log.final_decision.value if hasattr(log.final_decision, 'value') else log.final_decision,
                "facilitation_message": log.facilitation_message,
                "message_sent_at": log.message_sent_at.isoformat()
                if log.message_sent_at
                else None,
                "stage1_result": log.stage1_result,
                "stage2_result": log.stage2_result,
                "stage3_result": log.stage3_result,
            }
            for log in logs
        ]
