"""
SQLAlchemy database models for AIEngine.
Defines tables for groups, questions, messages, and facilitation logs.
"""

from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import List, Optional, AsyncGenerator

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    JSON,
    UniqueConstraint,
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


class Group(Base):
    """Group model storing group conversation metadata."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_id: Mapped[int] = mapped_column(
        Integer, unique=True, index=True, nullable=False
    )
    group_name: Mapped[str] = mapped_column(String(256), default="")
    last_ai_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    messages: Mapped[List["Message"]] = relationship(
        "Message", back_populates="group", cascade="all, delete-orphan"
    )
    facilitation_logs: Mapped[List["FacilitationLog"]] = relationship(
        "FacilitationLog", back_populates="group", cascade="all, delete-orphan"
    )
    members: Mapped[List["Member"]] = relationship(
        "Member", back_populates="group", cascade="all, delete-orphan"
    )
    group_questions: Mapped[List["GroupQuestion"]] = relationship(
        "GroupQuestion", back_populates="group", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Group(id={self.id}, external_id='{self.external_id}', group_name='{self.group_name}')>"


class QuestionOption(Base):
    """Question option model storing possible answer categories for questions."""

    __tablename__ = "question_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(String(256), nullable=False)

    # Relationships
    question: Mapped["Question"] = relationship("Question", back_populates="options")

    def __repr__(self) -> str:
        return f"<QuestionOption(id={self.id}, question_id={self.question_id}, text='{self.text}')>"


class Question(Base):
    """Question model storing unique discussion prompts."""

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_id: Mapped[str] = mapped_column(
        String(256), unique=True, index=True, nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    options: Mapped[List["QuestionOption"]] = relationship(
        "QuestionOption", back_populates="question", cascade="all, delete-orphan"
    )
    group_questions: Mapped[List["GroupQuestion"]] = relationship(
        "GroupQuestion", back_populates="question", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Question(id={self.id}, external_id='{self.external_id}', text='{self.text[:50]}...')>"


class GroupQuestion(Base):
    """
    Association table representing a question thread within a group.
    A pair of (group_id, question_id) identifies a unique conversation thread.
    """

    __tablename__ = "group_questions"
    __table_args__ = (
        UniqueConstraint("group_id", "question_id", name="uq_group_question"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("groups.id"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    unlock_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    group: Mapped["Group"] = relationship("Group", back_populates="group_questions")
    question: Mapped["Question"] = relationship(
        "Question", back_populates="group_questions"
    )
    messages: Mapped[List["Message"]] = relationship(
        "Message", back_populates="group_question", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<GroupQuestion(id={self.id}, group_id={self.group_id}, question_id={self.question_id}, status='{self.status}')>"


class User(Base):
    """User model storing user information across all groups."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_user_id: Mapped[str] = mapped_column(
        String(256), unique=True, index=True, nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(256), nullable=False)
    last_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    memberships: Mapped[List["Member"]] = relationship(
        "Member", back_populates="user", cascade="all, delete-orphan"
    )
    messages: Mapped[List["Message"]] = relationship(
        "Message", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, external_user_id='{self.external_user_id}', first_name='{self.first_name}', last_name='{self.last_name}')>"


class Member(Base):
    """Member model - join table linking users to groups."""

    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("groups.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    group: Mapped["Group"] = relationship("Group", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="memberships")

    def __repr__(self) -> str:
        return (
            f"<Member(id={self.id}, group_id={self.group_id}, user_id={self.user_id})>"
        )


class Message(Base):
    """Message model storing individual chat messages within question threads."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("groups.id"), nullable=False, index=True
    )
    group_question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("group_questions.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_ai: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    group: Mapped["Group"] = relationship("Group", back_populates="messages")
    group_question: Mapped["GroupQuestion"] = relationship(
        "GroupQuestion", back_populates="messages"
    )
    user: Mapped["User"] = relationship("User", back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, group_id={self.group_id}, group_question_id={self.group_question_id}, user_id={self.user_id}, content='{self.content[:30]}...')>"


class FacilitationLog(Base):
    """Facilitation log storing pipeline execution results."""

    __tablename__ = "facilitation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("groups.id"), nullable=False, index=True
    )
    group_question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("group_questions.id"), nullable=False, index=True
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Stage results stored as JSON
    stage1_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    stage2_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    stage3_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    stage4_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Final decision
    final_decision: Mapped[FacilitationDecision] = mapped_column(
        Enum(FacilitationDecision), nullable=False
    )

    # Generated facilitation message (if applicable)
    facilitation_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    group: Mapped["Group"] = relationship("Group", back_populates="facilitation_logs")
    group_question: Mapped["GroupQuestion"] = relationship("GroupQuestion")

    def __repr__(self) -> str:
        return f"<FacilitationLog(id={self.id}, group_id={self.group_id}, group_question_id={self.group_question_id}, decision={self.final_decision})>"


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
