"""
Pytest configuration and fixtures for AIEngine tests.
"""

import asyncio
from datetime import datetime, timedelta
from typing import AsyncGenerator, List

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.models.database import Base, Group, User, Question, GroupQuestion, Message
from app.services.llm_service import LLMService
from app.config import settings


# Configure pytest-asyncio
@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_engine():
    """Create test database engine."""
    # Use in-memory SQLite for tests
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    async_session_maker = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def test_group(db_session: AsyncSession) -> Group:
    """Create a test group."""
    group = Group(
        external_id=123,
        group_name="Test Group",
        created_at=datetime.now(),
        is_active=True
    )
    db_session.add(group)
    await db_session.flush()
    return group


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user."""
    user = User(
        external_user_id="test-user-1",
        first_name="John",
        last_name="Doe",
        created_at=datetime.now()
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def test_question(db_session: AsyncSession) -> Question:
    """Create a test question."""
    question = Question(
        external_id="test-question-1",
        text="What is your favorite memory?"
    )
    db_session.add(question)
    await db_session.flush()
    return question


@pytest_asyncio.fixture
async def test_group_question(
    db_session: AsyncSession,
    test_group: Group,
    test_question: Question
) -> GroupQuestion:
    """Create a test group-question thread."""
    group_question = GroupQuestion(
        group_id=test_group.id,
        question_id=test_question.id,
        status="active",
        unlock_order=1,
        created_at=datetime.now()
    )
    db_session.add(group_question)
    await db_session.flush()
    return group_question


@pytest_asyncio.fixture
async def test_messages(
    db_session: AsyncSession,
    test_group: Group,
    test_user: User,
    test_group_question: GroupQuestion
) -> List[Message]:
    """Create test messages."""
    base_time = datetime.now() - timedelta(hours=1)
    messages = []

    message_contents = [
        "I'm struggling with caregiving lately.",
        "It's really hard, I understand.",
        "Does anyone have advice?",
        "I find taking breaks helps.",
        "Thank you for sharing.",
    ]

    for i, content in enumerate(message_contents):
        msg = Message(
            group_id=test_group.id,
            group_question_id=test_group_question.id,
            user_id=test_user.id,
            content=content,
            timestamp=base_time + timedelta(minutes=i * 5),
            is_ai=False,
            created_at=datetime.now()
        )
        db_session.add(msg)
        messages.append(msg)

    await db_session.flush()

    # Refresh to load relationships
    for msg in messages:
        await db_session.refresh(msg, ['user'])

    return messages


@pytest.fixture
def mock_llm_verification_response():
    """Mock LLM verification response (Stage 2)."""
    return {
        "needs_facilitation": True,
        "reasoning": "The conversation shows low engagement and participants seeking advice.",
        "confidence": 0.85
    }


@pytest.fixture
def mock_llm_generation_response():
    """Mock LLM generation response (Stage 3)."""
    return {
        "facilitation_message": "It sounds like everyone is going through similar challenges. How are you all coping today?",
        "approach": "Open-ended question with emotional validation"
    }


@pytest.fixture
def mock_llm_no_facilitation_response():
    """Mock LLM response when facilitation is not needed."""
    return {
        "needs_facilitation": False,
        "reasoning": "The conversation is active and participants are supporting each other effectively.",
        "confidence": 0.90
    }
