"""
Facilitation service for running the pipeline on group-question threads.
"""

import logging
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Group, Question, GroupQuestion
from app.services.facilitator.pipeline import FacilitationDecisionPipeline
from app.services.message_service import MessageService
from app.config import settings

logger = logging.getLogger(__name__)


class FacilitationService:
    """Runs the facilitation pipeline for conversation threads."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.message_service = MessageService(session)
        self.pipeline = FacilitationDecisionPipeline()

    async def process_webhook_messages(
        self,
        group_question_id_pairs: List[Tuple[int, str]],
    ) -> List[Dict[str, Any]]:
        """
        Run the facilitation pipeline for the given (group_external_id, question_external_id) pairs.

        Args:
            group_question_id_pairs: List of (group_external_id, question_external_id) tuples

        Returns:
            List of dicts with 'group_id', 'question_id', 'message' for threads that need facilitation
        """
        facilitation_responses = []

        for group_external_id, question_external_id in group_question_id_pairs:
            try:
                response = await self._process_thread(group_external_id, question_external_id)
                if response:
                    facilitation_responses.append(response)
            except Exception as e:
                logger.error(
                    f"Error in facilitation for group {group_external_id}, "
                    f"question {question_external_id}: {e}",
                    exc_info=True,
                )

        return facilitation_responses

    async def _process_thread(
        self,
        group_external_id: int,
        question_external_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Run the facilitation pipeline for a single thread.

        Returns:
            Dict with group_id, question_id, message if facilitation is needed, else None
        """
        group = await self.message_service.get_group_by_external_id(group_external_id)
        if not group:
            logger.warning(f"Group {group_external_id} not found, skipping facilitation")
            return None

        question = await self.message_service.get_question_by_external_id(question_external_id)
        if not question:
            logger.warning(f"Question {question_external_id} not found, skipping facilitation")
            return None

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
            return None

        messages = await self.message_service.get_conversation_history(
            group=group,
            group_question=group_question,
        )

        if len(messages) < settings.min_messages:
            logger.info(
                f"Group {group_external_id}, question {question_external_id}: "
                f"only {len(messages)} messages (min {settings.min_messages}), skipping"
            )
            return None

        logger.info(
            f"Running facilitation pipeline for group {group_external_id}, "
            f"question {question_external_id} ({len(messages)} messages)"
        )

        pipeline_result = await self.pipeline.run_pipeline(
            topic=question.text,
            messages=messages,
        )

        sent_at = (
            datetime.now()
            if pipeline_result["final_decision"] == "FACILITATE"
            else None
        )

        await self.message_service.create_facilitation_log(
            group=group,
            group_question=group_question,
            stage1_result=pipeline_result.get("stage1"),
            stage2_result=pipeline_result.get("stage2"),
            stage3_result=pipeline_result.get("stage3"),
            final_decision=pipeline_result["final_decision"],
            facilitation_message=pipeline_result.get("facilitation_message"),
            message_sent_at=sent_at,
        )
        await self.session.commit()

        if pipeline_result["final_decision"] == "FACILITATE":
            return {
                "group_id": group_external_id,
                "question_id": question_external_id,
                "message": pipeline_result["facilitation_message"],
            }

        return None
