"""use timezone-aware datetime columns

Revision ID: a3f8c1d2e4b5
Revises: 2ea381fa6563
Create Date: 2026-03-26 17:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3f8c1d2e4b5"
down_revision: Union[str, Sequence[str], None] = "2ea381fa6563"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Columns to migrate to TIMESTAMP WITH TIME ZONE
# Format: (table_name, column_name, nullable)
DATETIME_COLUMNS = [
    ("groups", "last_ai_message_at", True),
    ("groups", "created_at", False),
    ("group_questions", "created_at", False),
    ("users", "created_at", False),
    ("members", "created_at", False),
    ("messages", "timestamp", False),
    ("messages", "created_at", False),
    ("facilitation_logs", "triggered_at", False),
    ("facilitation_logs", "message_sent_at", True),
]


def upgrade() -> None:
    """Convert all DateTime columns to TIMESTAMP WITH TIME ZONE."""
    for table, column, nullable in DATETIME_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=True),
            existing_type=sa.DateTime(timezone=False),
            existing_nullable=nullable,
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    """Revert to TIMESTAMP WITHOUT TIME ZONE."""
    for table, column, nullable in DATETIME_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=False),
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=nullable,
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )
