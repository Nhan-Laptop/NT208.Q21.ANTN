"""add ai detection rules table

Revision ID: 20260617_01
Revises: 20260603_01
Create Date: 2026-06-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260617_01"
down_revision = "20260603_01"
branch_labels = None
depends_on = None


rule_type = sa.Enum("phrase", "regex", "semantic", "hybrid", name="aidetectionruletype")
rule_severity = sa.Enum("low", "medium", "high", name="aidetectionruleseverity")
rule_scope = sa.Enum("user", "global", name="aidetectionrulescope")


def upgrade() -> None:
    op.create_table(
        "ai_detection_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("rule_type", rule_type, nullable=False),
        sa.Column("severity", rule_severity, nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("scope", rule_scope, nullable=False, server_default="user"),
        sa.Column("rule_json", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_detection_rules_owner_id"),
        "ai_detection_rules",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_detection_rules_owner_enabled",
        "ai_detection_rules",
        ["owner_id", "enabled"],
        unique=False,
    )
    op.create_index(
        "ix_ai_detection_rules_scope_enabled",
        "ai_detection_rules",
        ["scope", "enabled"],
        unique=False,
    )
    op.create_index(
        "ix_ai_detection_rules_created_at",
        "ai_detection_rules",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_detection_rules_created_at", table_name="ai_detection_rules")
    op.drop_index("ix_ai_detection_rules_scope_enabled", table_name="ai_detection_rules")
    op.drop_index("ix_ai_detection_rules_owner_enabled", table_name="ai_detection_rules")
    op.drop_index(op.f("ix_ai_detection_rules_owner_id"), table_name="ai_detection_rules")
    op.drop_table("ai_detection_rules")

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        rule_scope.drop(bind, checkfirst=True)
        rule_severity.drop(bind, checkfirst=True)
        rule_type.drop(bind, checkfirst=True)
