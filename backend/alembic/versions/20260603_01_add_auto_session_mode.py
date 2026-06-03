"""add auto session mode default

Revision ID: 20260603_01
Revises: 20260602_01
Create Date: 2026-06-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260603_01"
down_revision = "20260602_01"
branch_labels = None
depends_on = None


OLD_VALUES = (
    "general_qa",
    "verification",
    "journal_match",
    "retraction",
    "ai_detection",
)
NEW_VALUES = ("auto", *OLD_VALUES)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE sessionmode ADD VALUE IF NOT EXISTS 'auto'")
        op.execute("ALTER TABLE chat_sessions ALTER COLUMN mode SET DEFAULT 'auto'")
        return

    with op.batch_alter_table("chat_sessions") as batch:
        batch.alter_column(
            "mode",
            existing_type=sa.Enum(*OLD_VALUES, name="sessionmode"),
            type_=sa.Enum(*NEW_VALUES, name="sessionmode"),
            existing_nullable=False,
            server_default="auto",
        )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("UPDATE chat_sessions SET mode = 'general_qa' WHERE mode = 'auto'")

    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE chat_sessions ALTER COLUMN mode SET DEFAULT 'general_qa'")
        return

    with op.batch_alter_table("chat_sessions") as batch:
        batch.alter_column(
            "mode",
            existing_type=sa.Enum(*NEW_VALUES, name="sessionmode"),
            type_=sa.Enum(*OLD_VALUES, name="sessionmode"),
            existing_nullable=False,
            server_default="general_qa",
        )
