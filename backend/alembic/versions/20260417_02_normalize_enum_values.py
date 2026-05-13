"""normalize legacy enum values

Revision ID: 20260417_02
Revises: 20260417_01
Create Date: 2026-04-17 00:00:00.000000
"""

from alembic import op


revision = "20260417_02"
down_revision = "20260417_01"
branch_labels = None
depends_on = None


ENUM_COLUMNS = [
    ("users", "role", "userrole"),
    ("chat_sessions", "mode", "sessionmode"),
    ("chat_messages", "role", "messagerole"),
    ("chat_messages", "message_type", "messagetype"),
    ("venues", "venue_type", "venuetype"),
    ("crawl_jobs", "job_type", "crawljobtype"),
    ("crawl_jobs", "status", "crawljobstatus"),
    ("match_requests", "status", "matchrequeststatus"),
]


def _normalize_enum_column(table_name: str, column_name: str, enum_type: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f"""
            UPDATE {table_name}
            SET {column_name} = lower({column_name}::text)::{enum_type}
            WHERE {column_name}::text != lower({column_name}::text)
            """
        )
        return
    op.execute(
        f"""
        UPDATE {table_name}
        SET {column_name} = lower({column_name})
        WHERE {column_name} != lower({column_name})
        """
    )


def upgrade() -> None:
    for table_name, column_name, enum_type in ENUM_COLUMNS:
        _normalize_enum_column(table_name, column_name, enum_type)


def downgrade() -> None:
    # Data normalization is intentionally irreversible.
    pass
