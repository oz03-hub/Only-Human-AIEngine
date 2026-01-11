"""
Pydantic schemas for request/response validation.
Used by FastAPI for automatic validation and serialization.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

from app.models.database import FacilitationDecision


# ===== Webhook Schemas =====

class WebhookMessageRequest(BaseModel):
    """Incoming webhook payload from chat application."""

    group_id: str = Field(..., description="Chatroom UUID from external system")
    user_id: str = Field(..., description="User UUID who sent the message")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(..., description="ISO 8601 timestamp when message was sent")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "group_id": "chatroom-uuid-123",
                "user_id": "user-uuid-456",
                "content": "Hello everyone, how is everyone doing today?",
                "timestamp": "2024-01-15T14:30:00Z"
            }
        }
    )


class FacilitationResponse(BaseModel):
    """Outgoing facilitation message response."""

    group_id: str = Field(..., description="Chatroom UUID")
    message: str = Field(..., description="Generated facilitation message")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "group_id": "chatroom-uuid-123",
                "message": "It sounds like everyone is going through similar challenges..."
            }
        }
    )


# ===== Chatroom Schemas =====

class ChatroomBase(BaseModel):
    """Base chatroom schema."""
    external_id: str
    name: Optional[str] = None
    is_active: bool = True


class ChatroomCreate(ChatroomBase):
    """Schema for creating a new chatroom."""
    pass


class ChatroomResponse(ChatroomBase):
    """Schema for chatroom response."""
    id: int
    created_at: datetime
    last_activity: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ===== Message Schemas =====

class MessageBase(BaseModel):
    """Base message schema."""
    sender_id: str
    sender_name: str
    content: str
    timestamp: datetime


class MessageCreate(MessageBase):
    """Schema for creating a new message."""
    chatroom_id: int


class MessageResponse(MessageBase):
    """Schema for message response."""
    id: int
    chatroom_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===== Facilitation Log Schemas =====

class FacilitationLogBase(BaseModel):
    """Base facilitation log schema."""
    final_decision: FacilitationDecision
    facilitation_message: Optional[str] = None


class FacilitationLogCreate(FacilitationLogBase):
    """Schema for creating facilitation log."""
    chatroom_id: int
    stage1_result: Optional[dict] = None
    stage2_result: Optional[dict] = None
    stage3_result: Optional[dict] = None
    message_sent_at: Optional[datetime] = None


class FacilitationLogResponse(FacilitationLogBase):
    """Schema for facilitation log response."""
    id: int
    chatroom_id: int
    triggered_at: datetime
    stage1_result: Optional[dict] = None
    stage2_result: Optional[dict] = None
    stage3_result: Optional[dict] = None
    message_sent_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ===== API Response Schemas =====

class HealthCheckResponse(BaseModel):
    """Health check endpoint response."""
    status: str = "healthy"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    version: str = "1.0.0"


class ConversationHistoryResponse(BaseModel):
    """Conversation history response."""
    chatroom_id: int
    messages: List[MessageResponse]
    total_messages: int


class FacilitationCheckRequest(BaseModel):
    """Manual facilitation check request."""
    group_id: str = Field(..., description="Chatroom UUID to check")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "group_id": "chatroom-uuid-123"
            }
        }
    )


class FacilitationCheckResponse(BaseModel):
    """Facilitation check response."""
    group_id: str
    decision: FacilitationDecision
    message: Optional[str] = None
    log_id: int
