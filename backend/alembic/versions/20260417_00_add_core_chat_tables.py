"""add core auth chat tables

Revision ID: 20260417_00
Revises:
Create Date: 2026-04-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260417_00"
down_revision = None
branch_labels = None
depends_on = None


user_role = sa.Enum("admin", "researcher", name="userrole")
session_mode = sa.Enum(
    "general_qa",
    "verification",
    "journal_match",
    "retraction",
    "ai_detection",
    name="sessionmode",
)
message_role = sa.Enum("user", "assistant", "system", "tool", name="messagerole")
message_type = sa.Enum(
    "text",
    "citation_report",
    "journal_list",
    "retraction_report",
    "file_upload",
    "pdf_summary",
    "ai_writing_detection",
    "grammar_report",
    name="messagetype",
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("mode", session_mode, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_sessions_user_id"), "chat_sessions", ["user_id"], unique=False)

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("role", message_role, nullable=False),
        sa.Column("message_type", message_type, nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_results", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_messages_session_id"), "chat_messages", ["session_id"], unique=False)
    op.create_index("ix_chatmsg_session_created", "chat_messages", ["session_id", "created_at"], unique=False)

    op.create_table(
        "file_attachments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("storage_url", sa.Text(), nullable=False),
        sa.Column("storage_encrypted", sa.Boolean(), nullable=False),
        sa.Column("storage_encryption_alg", sa.String(length=64), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_file_attachments_message_id"), "file_attachments", ["message_id"], unique=False)
    op.create_index(op.f("ix_file_attachments_session_id"), "file_attachments", ["session_id"], unique=False)
    op.create_index(op.f("ix_file_attachments_user_id"), "file_attachments", ["user_id"], unique=False)
    op.create_index("ix_fileatt_session_created", "file_attachments", ["session_id", "created_at"], unique=False)
    op.create_index("ix_fileatt_user_created", "file_attachments", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("file_attachments")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("users")

    message_type.drop(op.get_bind(), checkfirst=True)
    message_role.drop(op.get_bind(), checkfirst=True)
    session_mode.drop(op.get_bind(), checkfirst=True)
    user_role.drop(op.get_bind(), checkfirst=True)
