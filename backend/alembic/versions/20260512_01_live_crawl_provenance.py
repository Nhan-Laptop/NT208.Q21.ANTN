"""add live crawl provenance fields

Revision ID: 20260512_01
Revises: 20260417_02
Create Date: 2026-05-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260512_01"
down_revision = "20260417_02"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _unique_constraint_names(table_name: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name)
        if constraint.get("name")
    }


def upgrade() -> None:
    raw_columns = _column_names("raw_source_snapshots")
    raw_columns_to_add = [
        column
        for column in [
            sa.Column("http_status", sa.Integer(), nullable=True),
            sa.Column("content_type", sa.String(length=255), nullable=True),
            sa.Column("content_length", sa.Integer(), nullable=True),
            sa.Column("storage_path", sa.String(length=1000), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("parser_version", sa.String(length=64), nullable=True),
            sa.Column("crawl_run_id", sa.String(length=64), nullable=True),
        ]
        if column.name not in raw_columns
    ]
    if raw_columns_to_add:
        with op.batch_alter_table("raw_source_snapshots") as batch:
            for column in raw_columns_to_add:
                batch.add_column(column)
    if "ix_raw_source_snapshots_crawl_run_id" not in _index_names("raw_source_snapshots"):
        op.create_index(op.f("ix_raw_source_snapshots_crawl_run_id"), "raw_source_snapshots", ["crawl_run_id"], unique=False)

    metric_columns = _column_names("venue_metrics")
    metric_columns_to_add = [
        column
        for column in [
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("metric_name", sa.String(length=128), nullable=True),
            sa.Column("metric_value", sa.Float(), nullable=True),
            sa.Column("metric_text", sa.Text(), nullable=True),
        ]
        if column.name not in metric_columns
    ]
    should_drop_old_unique = "uq_venue_metric_year" in _unique_constraint_names("venue_metrics")
    if should_drop_old_unique or metric_columns_to_add:
        with op.batch_alter_table("venue_metrics") as batch:
            if should_drop_old_unique:
                batch.drop_constraint("uq_venue_metric_year", type_="unique")
            for column in metric_columns_to_add:
                batch.add_column(column)
    metric_indexes = _index_names("venue_metrics")
    if "ix_venue_metrics_source_id" not in metric_indexes:
        op.create_index(op.f("ix_venue_metrics_source_id"), "venue_metrics", ["source_id"], unique=False)
    if "ix_venue_metrics_metric_name" not in metric_indexes:
        op.create_index(op.f("ix_venue_metrics_metric_name"), "venue_metrics", ["metric_name"], unique=False)


def downgrade() -> None:
    if "ix_venue_metrics_metric_name" in _index_names("venue_metrics"):
        op.drop_index(op.f("ix_venue_metrics_metric_name"), table_name="venue_metrics")
    if "ix_venue_metrics_source_id" in _index_names("venue_metrics"):
        op.drop_index(op.f("ix_venue_metrics_source_id"), table_name="venue_metrics")
    metric_columns = _column_names("venue_metrics")
    with op.batch_alter_table("venue_metrics") as batch:
        for column_name in ("metric_text", "metric_value", "metric_name", "source_id"):
            if column_name in metric_columns:
                batch.drop_column(column_name)
        if "uq_venue_metric_year" not in _unique_constraint_names("venue_metrics"):
            batch.create_unique_constraint("uq_venue_metric_year", ["venue_id", "metric_year"])

    if "ix_raw_source_snapshots_crawl_run_id" in _index_names("raw_source_snapshots"):
        op.drop_index(op.f("ix_raw_source_snapshots_crawl_run_id"), table_name="raw_source_snapshots")
    raw_columns = _column_names("raw_source_snapshots")
    with op.batch_alter_table("raw_source_snapshots") as batch:
        for column_name in (
            "crawl_run_id",
            "parser_version",
            "error_message",
            "storage_path",
            "content_length",
            "content_type",
            "http_status",
        ):
            if column_name in raw_columns:
                batch.drop_column(column_name)
