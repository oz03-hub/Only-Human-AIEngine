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
    Chatroom,
    Message,
    FacilitationLog,
    User,
    Member,
    Question,
    QuestionOption,
)
from app.models.schemas import (
    WebhookIncomingRequest,
    WebhookIncomingGroup,
    WebhookIncomingMessage,
    WebhookIncomingQuestion,
)

logger = logging.getLogger(__name__)


class MessageService:
    """Service for managing messages, users, chatrooms, and related entities."""

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

    # ===== Chatroom CRUD Operations =====

    async def get_or_create_chatroom(
        self,
        external_id: int,
        group_name: str = "",
        last_ai_message_at: Optional[datetime] = None,
    ) -> Chatroom:
        """
        Get existing chatroom or create new one.

        Args:
            external_id: External chatroom ID from the chat application
            group_name: Name of the chatroom
            last_ai_message_at: Timestamp of last AI message

        Returns:
            Chatroom object
        """
        # Try to get existing chatroom
        result = await self.session.execute(
            select(Chatroom).where(Chatroom.external_id == external_id)
        )
        chatroom = result.scalar_one_or_none()

        if chatroom:
            return chatroom

        # Create new chatroom
        chatroom = Chatroom(
            external_id=external_id,
            group_name=group_name,
            last_ai_message_at=last_ai_message_at,
            created_at=datetime.now(),
        )
        self.session.add(chatroom)
        await self.session.flush()
        logger.info(f"Created new chatroom: {external_id} ({group_name})")

        return chatroom

    async def update_chatroom_active_status(
        self, external_id: int, new_status: bool
    ) -> Optional[Chatroom]:
        """
        Update chatroom activeness status by external ID.

        Args:
            external_id: External chatroom ID
            new_status: True or False to indicate activity

        Returns:
            Chatroom object or None
        """

        result = await self.session.execute(
            select(Chatroom).where(Chatroom.external_id == external_id)
        )
        chatroom = result.scalar_one_or_none()

        if chatroom:
            # Update chatroom activity
            chatroom.is_active = new_status
            await self.session.flush()

        return chatroom

    async def get_chatroom_by_external_id(self, external_id: int) -> Optional[Chatroom]:
        """
        Get chatroom by external ID.

        Args:
            external_id: External chatroom ID

        Returns:
            Chatroom object or None
        """
        result = await self.session.execute(
            select(Chatroom).where(Chatroom.external_id == external_id)
        )
        return result.scalar_one_or_none()

    # ===== Member CRUD Operations =====

    async def get_or_create_member(self, chatroom: Chatroom, user: User) -> Member:
        """
        Get existing member or create new one (join user to chatroom).

        Args:
            chatroom: Chatroom object
            user: User object

        Returns:
            Member object
        """
        # Try to get existing membership
        result = await self.session.execute(
            select(Member).where(
                and_(Member.chatroom_id == chatroom.id, Member.user_id == user.id)
            )
        )
        member = result.scalar_one_or_none()

        if member:
            return member

        # Create new membership
        member = Member(
            chatroom_id=chatroom.id,
            user_id=user.id,
            created_at=datetime.now(),
        )
        self.session.add(member)
        await self.session.flush()
        logger.info(
            f"Added user {user.external_user_id} to chatroom {chatroom.external_id}"
        )

        return member

    # ===== Question CRUD Operations =====

    async def get_or_create_question(
        self,
        chatroom: Chatroom,
        external_id: str,
        text: str,
        status: str,
        unlock_order: int,
    ) -> Question:
        """
        Get existing question or create new one.

        Args:
            chatroom: Chatroom object
            external_id: External question ID
            text: Question text
            status: Question status (active, inactive)
            unlock_order: Order in which question is unlocked

        Returns:
            Question object
        """
        # Try to get existing question
        result = await self.session.execute(
            select(Question).where(Question.external_id == external_id)
        )
        question = result.scalar_one_or_none()

        if question:
            # Update question info if changed
            updated = False
            if question.text != text:
                question.text = text
                updated = True
            if question.status != status:
                question.status = status
                updated = True
            if question.unlock_order != unlock_order:
                question.unlock_order = unlock_order
                updated = True

            if updated:
                await self.session.flush()
                logger.debug(f"Updated question: {external_id}")

            return question

        # Create new question
        question = Question(
            external_id=external_id,
            chatroom_id=chatroom.id,
            text=text,
            status=status,
            unlock_order=unlock_order,
        )
        self.session.add(question)
        await self.session.flush()
        logger.info(
            f"Created new question: {external_id} in chatroom {chatroom.external_id}"
        )

        return question

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
        chatroom: Chatroom,
        user: User,
        content: str,
        timestamp: datetime,
        question: Optional[Question] = None,
        is_ai: bool = False,
    ) -> Message:
        """
        Create a new message in the database.

        Args:
            chatroom: Chatroom object
            user: User object
            content: Message content
            timestamp: Message timestamp
            question: Optional Question object the message is responding to
            is_ai: Whether the message was generated by AI

        Returns:
            Created Message object
        """
        message = Message(
            chatroom_id=chatroom.id,
            user_id=user.id,
            question_id=question.id if question else None,
            content=content,
            timestamp=timestamp,
            is_ai=is_ai,
            created_at=datetime.now(),
        )
        self.session.add(message)
        await self.session.flush()
        logger.debug(
            f"Created message {message.id} in chatroom {chatroom.external_id} "
            f"(question: {question.external_id if question else 'None'}, is_ai: {is_ai})"
        )

        return message

    async def get_conversation_history(
        self,
        chatroom: Chatroom,
        limit: Optional[int] = None,
        since: Optional[datetime] = None,
    ) -> List[Message]:
        """
        Get conversation history for a chatroom.

        Args:
            chatroom: Chatroom object
            limit: Maximum number of messages to retrieve (most recent)
            since: Only get messages after this timestamp

        Returns:
            List of Message objects ordered by timestamp
        """
        query = select(Message).where(Message.chatroom_id == chatroom.id)

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
        messages_by_group: Dict[int, List[Message]] = {}
        groups: List[WebhookIncomingGroup] = webhook_content.groups

        for group in groups:
            group_id: int = group.group_id
            messages_by_group[group_id] = []

            # Create/update chatroom
            chatroom = await self.get_or_create_chatroom(
                external_id=group_id,
                group_name=group.group_name,
                last_ai_message_at=group.last_ai_message_at,
            )

            # Create/update members
            for member_data in group.members:
                user = await self.get_or_create_user(
                    external_user_id=member_data.user_id,
                    first_name=member_data.first_name,
                    last_name=member_data.last_name,
                )
                await self.get_or_create_member(chatroom=chatroom, user=user)

            # Create/update questions and their options
            for question_data in group.questions:
                question = await self.get_or_create_question(
                    chatroom=chatroom,
                    external_id=question_data.id,
                    text=question_data.text,
                    status=question_data.status,
                    unlock_order=question_data.unlock_order,
                )
                await self.create_or_update_question_options(
                    question=question, options=question_data.options
                )

            # Create messages
            new_messages: List[WebhookIncomingMessage] = group.messages
            for message_data in new_messages:
                # Get user
                user = await self.get_or_create_user(
                    external_user_id=message_data.user_id,
                    first_name=message_data.first_name,
                    last_name=message_data.last_name,
                )

                # Get question if message is associated with one
                question = None
                if message_data.question_id:
                    question = await self.get_question_by_external_id(
                        message_data.question_id
                    )
                    if not question:
                        logger.warning(
                            f"Question {message_data.question_id} not found for message"
                        )

                # Create message
                message = await self.create_message(
                    chatroom=chatroom,
                    user=user,
                    content=message_data.content,
                    timestamp=message_data.created_at,
                    question=question,
                    is_ai=message_data.is_ai,
                )

                messages_by_group[group_id].append(message)

        await self.session.commit()
        logger.info(
            f"Stored webhook content: {len(groups)} groups, "
            f"{sum(len(msgs) for msgs in messages_by_group.values())} messages"
        )

        return messages_by_group

    # ===== Facilitation Log CRUD Operations =====

    async def get_last_facilitation_time(
        self, chatroom: Chatroom
    ) -> Optional[datetime]:
        """
        Get timestamp of the last facilitation for a chatroom.

        Args:
            chatroom: Chatroom object

        Returns:
            Datetime of last facilitation or None
        """
        result = await self.session.execute(
            select(FacilitationLog.message_sent_at)
            .where(
                and_(
                    FacilitationLog.chatroom_id == chatroom.id,
                    FacilitationLog.message_sent_at.isnot(None),
                )
            )
            .order_by(desc(FacilitationLog.message_sent_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_facilitation_log(
        self,
        chatroom: Chatroom,
        stage1_result: Optional[Dict[str, Any]],
        stage2_result: Optional[Dict[str, Any]],
        stage3_result: Optional[Dict[str, Any]],
        final_decision: str,
        facilitation_message: Optional[str] = None,
        message_sent_at: Optional[datetime] = None,
    ) -> FacilitationLog:
        """
        Create a facilitation log entry.

        Args:
            chatroom: Chatroom object
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
            chatroom_id=chatroom.id,
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
            f"Created facilitation log {log.id} for chatroom {chatroom.external_id}: {final_decision}"
        )

        return log
