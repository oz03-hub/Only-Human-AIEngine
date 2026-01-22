"""
SQLAlchemy database models for AIEngine.
Defines tables for chatrooms, messages, and facilitation logs.
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import List, Optional, AsyncGenerator

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    JSON,
    create_engine,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column

from app.config import settings


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class FacilitationDecision(str, PyEnum):
    """Enum for final facilitation decision."""

    NO_FACILITATION = "NO_FACILITATION"
    NO_FACILITATION_AFTER_VERIFY = "NO_FACILITATION_AFTER_VERIFY"
    FACILITATE = "FACILITATE"


class Chatroom(Base):
    """Chatroom model storing group conversation metadata."""

    __tablename__ = "chatrooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_id: Mapped[int] = mapped_column(
        Integer, unique=True, index=True, nullable=False
    )
    group_name: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(), nullable=False
    )

    # Relationships
    messages: Mapped[List["Message"]] = relationship(
        "Message", back_populates="chatroom", cascade="all, delete-orphan"
    )
    facilitation_logs: Mapped[List["FacilitationLog"]] = relationship(
        "FacilitationLog", back_populates="chatroom", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Chatroom(id={self.id}, external_id='{self.external_id}', group_name='{self.group_name}')>"


class QuestionOption(Base):
    __tablename__ = "question_options"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    text: Mapped[str] = mapped_column(String(256), nullable=False)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64))
    unlock_order: Mapped[int] = mapped_column(SmallInteger)


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(256), unique=True)
    first_name: Mapped[str] = mapped_column(String(256))
    last_name: Mapped[str] = mapped_column(String(256))

    def __repr__(self) -> str:
        return f"<Member(id={self.id}, user_id='{self.user_id}', first_name='{self.first_name}')>"


class Message(Base):
    """Message model storing individual chat messages."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    chatroom_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chatrooms.id"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(), nullable=False
    )
    is_ai: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Relationships
    chatroom: Mapped["Chatroom"] = relationship("Chatroom", back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, chatroom_id={self.chatroom_id}, user_id={self.user_id}, content={self.content})>"


class FacilitationLog(Base):
    """Facilitation log storing pipeline execution results."""

    __tablename__ = "facilitation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    chatroom_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chatrooms.id"), nullable=False, index=True
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(), nullable=False
    )

    # Stage results stored as JSON
    stage1_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    stage2_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    stage3_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Final decision
    final_decision: Mapped[FacilitationDecision] = mapped_column(
        Enum(FacilitationDecision), nullable=False
    )

    # Generated facilitation message (if applicable)
    facilitation_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    chatroom: Mapped["Chatroom"] = relationship(
        "Chatroom", back_populates="facilitation_logs"
    )

    def __repr__(self) -> str:
        return f"<FacilitationLog(id={self.id}, chatroom_id={self.chatroom_id}, decision={self.final_decision})>"


# Database engine and session factory
engine = create_async_engine(
    settings.database_url, echo=(settings.env == "development"), future=True
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency function to get database session.
    Used with FastAPI's dependency injection.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
