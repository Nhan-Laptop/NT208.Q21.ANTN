"""add source_url to venues

Revision ID: 20260627_01
Revises: 20260617_01
Create Date: 2026-06-27 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260627_01"
down_revision = "20260617_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("venues") as batch:
        batch.add_column(sa.Column("source_url", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("venues") as batch:
        batch.drop_column("source_url")
