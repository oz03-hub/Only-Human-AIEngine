"""
Message service for CRUD operations on messages and chatrooms.
Handles all database operations related to messages.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.database import Chatroom, Message, FacilitationLog
from app.models.schemas import WebhookIncomingRequest, WebhookIncomingGroup, WebhookIncomingMessage

logger = logging.getLogger(__name__)


class MessageService:
    """Service for managing messages and chatrooms."""

    def __init__(self, session: AsyncSession):
        """
        Initialize message service.

        Args:
            session: Database session
        """
        self.session = session

    async def get_or_create_chatroom(self, external_id: int) -> Chatroom:
        """
        Get existing chatroom or create new one.

        Args:
            external_id: External chatroom ID from the chat application

        Returns:
            Chatroom object
        """
        # Try to get existing chatroom
        result = await self.session.execute(
            select(Chatroom).where(Chatroom.external_id == external_id)
        )
        chatroom = result.scalar_one_or_none()

        if chatroom:
            logger.debug(f"Found existing chatroom: {external_id}")
            return chatroom

        # Create new chatroom
        chatroom = Chatroom(
            external_id=external_id,
            created_at=datetime.now(),
        )
        self.session.add(chatroom)
        await self.session.flush()  # Flush to get the ID
        logger.info(f"Created new chatroom: {external_id}")

        return chatroom

    async def create_message(
        self,
        chatroom: Chatroom,
        user_id: str,
        content: str,
        timestamp: datetime
    ) -> Message:
        """
        Create a new message in the database.

        Args:
            chatroom: Chatroom object
            user_id: ID of the message sender
            content: Message content
            timestamp: Message timestamp

        Returns:
            Created Message object
        """
        message = Message(
            chatroom_id=chatroom.id,
            user_id=user_id,
            content=content,
            timestamp=timestamp,
            created_at=datetime.now()
        )
        self.session.add(message)
        await self.session.flush()
        logger.debug(f"Created message {message.id} in chatroom {chatroom.external_id}")

        return message

    async def store_webhook_content(self, webhook_content: WebhookIncomingRequest) -> Dict[int, Dict]:
        """
        Store messages from webhook payload

        Args:
            webhook_content (WebhookIncomingRequest): Object that contains a list of groups and their new messages
        """

        messages_by_group: Dict[int, List[Message]] = {}
        groups: List[WebhookIncomingGroup] = webhook_content.groups

        for group in groups:
            group_id: int = group.group_id
            messages_by_group[group_id] = []
            chatroom = await self.get_or_create_chatroom(group_id)
            new_messages: List[WebhookIncomingMessage] = group.messages

            for new_message in new_messages:
                message = await self.create_message(
                    chatroom=chatroom,
                    user_id=new_message.user_id,
                    content=new_message.content,
                    timestamp=new_message.created_at
                )

                messages_by_group[group_id].append(message)
        await self.session.commit()
        return messages_by_group

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

    async def get_conversation_history(
        self,
        chatroom: Chatroom,
        limit: Optional[int] = None,
        since: Optional[datetime] = None
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

    async def get_last_facilitation_time(self, chatroom: Chatroom) -> Optional[datetime]:
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
                    FacilitationLog.message_sent_at.isnot(None)
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
        message_sent_at: Optional[datetime] = None
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
            message_sent_at=message_sent_at
        )
        self.session.add(log)
        await self.session.flush()
        logger.info(f"Created facilitation log {log.id} for chatroom {chatroom.external_id}: {final_decision}")

        return log
