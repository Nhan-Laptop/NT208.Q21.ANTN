"""add user ai detection rule preferences

Revision ID: 20260602_01
Revises: 20260512_01
Create Date: 2026-06-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260602_01"
down_revision = "20260512_01"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    user_columns = _column_names("users")
    if "ai_detection_rule_prefs" not in user_columns:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("ai_detection_rule_prefs", sa.Text(), nullable=True))


def downgrade() -> None:
    user_columns = _column_names("users")
    if "ai_detection_rule_prefs" in user_columns:
        with op.batch_alter_table("users") as batch:
            batch.drop_column("ai_detection_rule_prefs")
