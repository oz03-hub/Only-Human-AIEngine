"""
Message service for CRUD operations on messages and chatrooms.
Handles all database operations related to messages, users, questions, and facilitation.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.database import (
    Group,
    Message,
    FacilitationLog,
    User,
    Member,
    Question,
    QuestionOption,
    GroupQuestion,
)
from app.models.schemas import (
    WebhookIncomingRequest,
    WebhookIncomingGroup,
    WebhookIncomingMessage,
    WebhookIncomingQuestion,
)

logger = logging.getLogger(__name__)


class MessageService:
    """Service for managing messages, users, groups, and related entities."""

    def __init__(self, session: AsyncSession):
        """
        Initialize message service.

        Args:
            session: Database session
        """
        self.session = session

    # ===== User CRUD Operations =====

    async def get_or_create_user(
        self, external_user_id: str, first_name: str, last_name: str
    ) -> User:
        """
        Get existing user or create new one.

        Args:
            external_user_id: External user ID from the chat application
            first_name: User's first name
            last_name: User's last name

        Returns:
            User object
        """
        # Try to get existing user
        result = await self.session.execute(
            select(User).where(User.external_user_id == external_user_id)
        )
        user = result.scalar_one_or_none()

        if user:
            return user

        # Create new user
        user = User(
            external_user_id=external_user_id,
            first_name=first_name,
            last_name=last_name,
            created_at=datetime.now(),
        )
        self.session.add(user)
        await self.session.flush()
        logger.info(f"Created new user: {external_user_id}")

        return user

    # ===== Group CRUD Operations =====

    async def get_or_create_group(
        self,
        external_id: int,
        group_name: str = "",
        last_ai_message_at: Optional[datetime] = None,
    ) -> Group:
        """
        Get existing group or create new one.

        Args:
            external_id: External group ID from the chat application
            group_name: Name of the group
            last_ai_message_at: Timestamp of last AI message

        Returns:
            Group object
        """
        # Try to get existing group
        result = await self.session.execute(
            select(Group).where(Group.external_id == external_id)
        )
        group = result.scalar_one_or_none()

        if group:
            return group

        # Create new group
        group = Group(
            external_id=external_id,
            group_name=group_name,
            last_ai_message_at=last_ai_message_at,
            created_at=datetime.now(),
        )
        self.session.add(group)
        await self.session.flush()
        logger.info(f"Created new group: {external_id} ({group_name})")

        return group

    async def update_group_active_status(
        self, external_id: int, new_status: bool
    ) -> Optional[Group]:
        """
        Update group activeness status by external ID.

        Args:
            external_id: External group ID
            new_status: True or False to indicate activity

        Returns:
            Group object or None
        """

        result = await self.session.execute(
            select(Group).where(Group.external_id == external_id)
        )
        group = result.scalar_one_or_none()

        if group:
            # Update group activity
            group.is_active = new_status
            await self.session.flush()

        return group

    async def get_group_by_external_id(self, external_id: int) -> Optional[Group]:
        """
        Get group by external ID.

        Args:
            external_id: External group ID

        Returns:
            Group object or None
        """
        result = await self.session.execute(
            select(Group).where(Group.external_id == external_id)
        )
        return result.scalar_one_or_none()

    # ===== Member CRUD Operations =====

    async def get_or_create_member(self, group: Group, user: User) -> Member:
        """
        Get existing member or create new one (join user to group).

        Args:
            group: Group object
            user: User object

        Returns:
            Member object
        """
        # Try to get existing membership
        result = await self.session.execute(
            select(Member).where(
                and_(Member.group_id == group.id, Member.user_id == user.id)
            )
        )
        member = result.scalar_one_or_none()

        if member:
            return member

        # Create new membership
        member = Member(
            group_id=group.id,
            user_id=user.id,
            created_at=datetime.now(),
        )
        self.session.add(member)
        await self.session.flush()
        logger.info(f"Added user {user.external_user_id} to group {group.external_id}")

        return member

    # ===== Question CRUD Operations =====

    async def update_group_question_status(
        self, group_external_id: int, question_external_id: str, new_status: str
    ) -> Optional[GroupQuestion]:
        """
        Update existing group question status.

        Args:
            group_external_id: External ID of the group
            question_external_id: External ID of the question
            new_status: New status for the group question

        Returns:
            GroupQuestion object if found and updated, None otherwise
        """
        # Get group by external ID
        result = await self.session.execute(
            select(Group).where(Group.external_id == group_external_id)
        )
        group = result.scalar_one_or_none()

        if not group:
            logger.warning(
                f"Cannot update question status: Group {group_external_id} not found"
            )
            return None

        # Get question by external ID
        result = await self.session.execute(
            select(Question).where(Question.external_id == question_external_id)
        )
        question = result.scalar_one_or_none()

        if not question:
            logger.warning(
                f"Cannot update question status: Question {question_external_id} not found"
            )
            return None

        # Get GroupQuestion association
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
                f"Cannot update question status: GroupQuestion not found for "
                f"group {group_external_id}, question {question_external_id}"
            )
            return None

        # Update status if it changed
        if group_question.status != new_status:
            old_status = group_question.status
            group_question.status = new_status
            await self.session.flush()
            logger.info(
                f"Updated GroupQuestion status for group {group_external_id}, "
                f"question {question_external_id}: {old_status} → {new_status}"
            )
        else:
            logger.debug(
                f"GroupQuestion status unchanged for group {group_external_id}, "
                f"question {question_external_id}: {new_status}"
            )

        return group_question

    async def get_or_create_question(
        self,
        external_id: str,
        text: str,
    ) -> Question:
        """
        Get existing question or create new one.
        Questions are global entities that can be used across multiple groups.

        Args:
            external_id: External question ID
            text: Question text

        Returns:
            Question object
        """
        # Try to get existing question
        result = await self.session.execute(
            select(Question).where(Question.external_id == external_id)
        )
        question = result.scalar_one_or_none()

        if question:
            # Update question text if changed
            if question.text != text:
                question.text = text
                await self.session.flush()
                logger.debug(f"Updated question: {external_id}")

            return question

        # Create new question
        question = Question(
            external_id=external_id,
            text=text,
        )
        self.session.add(question)
        await self.session.flush()
        logger.info(f"Created new question: {external_id}")

        return question

    async def get_or_create_group_question(
        self,
        group: Group,
        question: Question,
        status: str,
        unlock_order: int,
    ) -> GroupQuestion:
        """
        Get existing group-question thread or create new one.
        A GroupQuestion represents a question thread within a specific group.

        Args:
            group: Group object
            question: Question object
            status: Question status in this group (active, inactive, etc.)
            unlock_order: Order in which question is unlocked in this group

        Returns:
            GroupQuestion object
        """
        # Try to get existing group-question association
        result = await self.session.execute(
            select(GroupQuestion).where(
                and_(
                    GroupQuestion.group_id == group.id,
                    GroupQuestion.question_id == question.id,
                )
            )
        )
        group_question = result.scalar_one_or_none()

        if group_question:
            # Update status and unlock_order if changed
            updated = False
            if group_question.status != status:
                group_question.status = status
                updated = True
            if group_question.unlock_order != unlock_order:
                group_question.unlock_order = unlock_order
                updated = True

            if updated:
                await self.session.flush()
                logger.debug(
                    f"Updated GroupQuestion for group {group.external_id}, "
                    f"question {question.external_id}"
                )

            return group_question

        # Create new group-question association
        group_question = GroupQuestion(
            group_id=group.id,
            question_id=question.id,
            status=status,
            unlock_order=unlock_order,
            created_at=datetime.now(),
        )
        self.session.add(group_question)
        await self.session.flush()
        logger.info(
            f"Created GroupQuestion thread for group {group.external_id}, "
            f"question {question.external_id}"
        )

        return group_question

    async def create_or_update_question_options(
        self, question: Question, options: List[str]
    ) -> List[QuestionOption]:
        """
        Create or update question options.

        Args:
            question: Question object
            options: List of option texts

        Returns:
            List of QuestionOption objects
        """
        # Get existing options
        result = await self.session.execute(
            select(QuestionOption).where(QuestionOption.question_id == question.id)
        )
        existing_options = list(result.scalars().all())

        # Convert to dict for easy lookup
        existing_by_text = {opt.text: opt for opt in existing_options}

        # Track which options to keep
        current_option_texts = set(options)
        existing_option_texts = set(existing_by_text.keys())

        # Delete options that no longer exist
        options_to_delete = existing_option_texts - current_option_texts
        for text_to_delete in options_to_delete:
            opt = existing_by_text[text_to_delete]
            await self.session.delete(opt)
            logger.debug(
                f"Deleted option '{text_to_delete}' from question {question.external_id}"
            )

        # Add new options
        options_to_add = current_option_texts - existing_option_texts
        for text_to_add in options_to_add:
            new_opt = QuestionOption(question_id=question.id, text=text_to_add)
            self.session.add(new_opt)
            logger.debug(
                f"Added option '{text_to_add}' to question {question.external_id}"
            )

        await self.session.flush()

        # Return all current options
        result = await self.session.execute(
            select(QuestionOption).where(QuestionOption.question_id == question.id)
        )
        return list(result.scalars().all())

    async def get_question_by_external_id(self, external_id: str) -> Optional[Question]:
        """
        Get question by external ID.

        Args:
            external_id: External question ID

        Returns:
            Question object or None
        """
        result = await self.session.execute(
            select(Question).where(Question.external_id == external_id)
        )
        return result.scalar_one_or_none()

    # ===== Message CRUD Operations =====

    async def create_message(
        self,
        group: Group,
        user: User,
        content: str,
        timestamp: datetime,
        group_question: GroupQuestion,
        is_ai: bool = False,
    ) -> Message:
        """
        Create a new message in the database.

        Args:
            group: Group object
            user: User object
            content: Message content
            timestamp: Message timestamp
            group_question: GroupQuestion object (thread) the message belongs to
            is_ai: Whether the message was generated by AI

        Returns:
            Created Message object
        """
        message = Message(
            group_id=group.id,
            user_id=user.id,
            group_question_id=group_question.id,
            content=content,
            timestamp=timestamp,
            is_ai=is_ai,
            created_at=datetime.now(),
        )
        self.session.add(message)
        await self.session.flush()
        logger.debug(
            f"Created message {message.id} in group {group.external_id} "
            f"(group_question: {group_question.id}, is_ai: {is_ai})"
        )

        return message

    async def get_conversation_history(
        self,
        group: Group,
        group_question: Optional[GroupQuestion] = None,
        limit: Optional[int] = None,
        since: Optional[datetime] = None,
    ) -> List[Message]:
        """
        Get conversation history for a group, optionally filtered by question thread.

        Args:
            group: Group object
            group_question: Optional GroupQuestion to filter messages by thread
            limit: Maximum number of messages to retrieve (most recent)
            since: Only get messages after this timestamp

        Returns:
            List of Message objects ordered by timestamp (with user relationship loaded)
        """
        query = (
            select(Message)
            .where(Message.group_id == group.id)
            .options(selectinload(Message.user))  # Eagerly load user relationship
        )

        if group_question:
            query = query.where(Message.group_question_id == group_question.id)

        if since:
            query = query.where(Message.timestamp >= since)

        query = query.order_by(Message.timestamp.asc())

        if limit:
            # Get all messages first, then slice to get the most recent N
            result = await self.session.execute(query)
            all_messages = list(result.scalars().all())
            return all_messages[-limit:] if len(all_messages) > limit else all_messages

        result = await self.session.execute(query)
        return list(result.scalars().all())

    # ===== Webhook Processing =====

    async def store_webhook_content(
        self, webhook_content: WebhookIncomingRequest
    ) -> Dict[int, List[Message]]:
        """
        Store all data from webhook payload (groups, members, questions, messages).

        Args:
            webhook_content: Webhook payload containing groups and messages

        Returns:
            Dictionary mapping group_id to list of created Message objects
        """
        messages_by_group_by_question: Dict[int, Dict[int, List[str]]] = {}
        groups: List[WebhookIncomingGroup] = webhook_content.groups

        for group_data in groups:
            group_id: int = group_data.group_id
            messages_by_group_by_question[group_id] = {}

            # Create/update group
            group = await self.get_or_create_group(
                external_id=group_id,
                group_name=group_data.group_name,
                last_ai_message_at=group_data.last_ai_message_at,
            )

            # Create/update members
            for member_data in group_data.members:
                user = await self.get_or_create_user(
                    external_user_id=member_data.user_id,
                    first_name=member_data.first_name,
                    last_name=member_data.last_name,
                )
                await self.get_or_create_member(group=group, user=user)

            # Create/update questions, group-question threads, and options
            # Map question external_id to GroupQuestion object for message creation
            group_question_map: Dict[str, GroupQuestion] = {}

            for question_data in group_data.questions:
                # Create/update the global Question
                question = await self.get_or_create_question(
                    external_id=question_data.id,
                    text=question_data.text,
                )

                # Create/update question options
                await self.create_or_update_question_options(
                    question=question, options=question_data.options
                )

                # Create/update the GroupQuestion thread
                group_question = await self.get_or_create_group_question(
                    group=group,
                    question=question,
                    status=question_data.status,
                    unlock_order=question_data.unlock_order,
                )

                # Store mapping for message creation
                group_question_map[question_data.id] = group_question
                messages_by_group_by_question[group_id][question_data.id] = []

            # Create messages
            new_messages: List[WebhookIncomingMessage] = group_data.messages
            for message_data in new_messages:
                # Get user
                user = await self.get_or_create_user(
                    external_user_id=message_data.user_id,
                    first_name=message_data.first_name,
                    last_name=message_data.last_name,
                )

                # Get GroupQuestion for this message
                group_question = group_question_map.get(message_data.question_id)
                if not group_question:
                    logger.warning(
                        f"GroupQuestion for question_id {message_data.question_id} "
                        f"not found in group {group_id}. Skipping message."
                    )
                    continue

                # Create message
                message = await self.create_message(
                    group=group,
                    user=user,
                    content=message_data.content,
                    timestamp=message_data.created_at,
                    group_question=group_question,
                    is_ai=message_data.is_ai,
                )

                # Use the external_id from webhook data instead of accessing relationship
                messages_by_group_by_question[group_id][
                    message_data.question_id
                ].append(message)

        await self.session.commit()
        logger.info(
            f"Stored webhook content: {len(groups)} groups,"
            f"{sum(len(qs) for qs in messages_by_group_by_question.values())} group questions,"
            f"{sum(len(q) for qs in messages_by_group_by_question.values() for q in qs.values())} total messages."
        )

        return messages_by_group_by_question

    # ===== Facilitation Log CRUD Operations =====

    async def get_last_facilitation_time(
        self, group: Group, group_question: Optional[GroupQuestion] = None
    ) -> Optional[datetime]:
        """
        Get timestamp of the last facilitation for a group or group-question thread.

        Args:
            group: Group object
            group_question: Optional GroupQuestion to filter by specific thread

        Returns:
            Datetime of last facilitation or None
        """
        conditions = [
            FacilitationLog.group_id == group.id,
            FacilitationLog.message_sent_at.isnot(None),
        ]

        if group_question:
            conditions.append(FacilitationLog.group_question_id == group_question.id)

        result = await self.session.execute(
            select(FacilitationLog.message_sent_at)
            .where(and_(*conditions))
            .order_by(desc(FacilitationLog.message_sent_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_facilitation_log(
        self,
        group: Group,
        group_question: GroupQuestion,
        stage1_result: Optional[Dict[str, Any]],
        stage2_result: Optional[Dict[str, Any]],
        stage3_result: Optional[Dict[str, Any]],
        final_decision: str,
        facilitation_message: Optional[str] = None,
        message_sent_at: Optional[datetime] = None,
    ) -> FacilitationLog:
        """
        Create a facilitation log entry for a group-question thread.

        Args:
            group: Group object
            group_question: GroupQuestion object (thread)
            stage1_result: Stage 1 result dict
            stage2_result: Stage 2 result dict
            stage3_result: Stage 3 result dict
            final_decision: Final decision (NO_FACILITATION, NO_FACILITATION_AFTER_VERIFY, FACILITATE)
            facilitation_message: Generated facilitation message
            message_sent_at: Timestamp when message was sent

        Returns:
            Created FacilitationLog object
        """
        log = FacilitationLog(
            group_id=group.id,
            group_question_id=group_question.id,
            triggered_at=datetime.now(),
            stage1_result=stage1_result,
            stage2_result=stage2_result,
            stage3_result=stage3_result,
            final_decision=final_decision,
            facilitation_message=facilitation_message,
            message_sent_at=message_sent_at,
        )
        self.session.add(log)
        await self.session.flush()
        logger.info(
            f"Created facilitation log {log.id} for group {group.external_id}, "
            f"thread {group_question.id}: {final_decision}"
        )

        return log
