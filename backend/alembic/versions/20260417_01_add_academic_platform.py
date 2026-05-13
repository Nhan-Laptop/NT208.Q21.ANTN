"""add academic platform tables

Revision ID: 20260417_01
Revises:
Create Date: 2026-04-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260417_01"
down_revision = "20260417_00"
branch_labels = None
depends_on = None


crawl_job_status = sa.Enum("pending", "running", "succeeded", "failed", name="crawljobstatus")
crawl_job_type = sa.Enum("crawl", "reindex", name="crawljobtype")
venue_type = sa.Enum("journal", "conference", "workshop", "cfp", name="venuetype")
match_request_status = sa.Enum("pending", "running", "succeeded", "failed", name="matchrequeststatus")


def upgrade() -> None:
    op.create_table(
        "crawl_sources",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_crawl_sources_slug"), "crawl_sources", ["slug"], unique=True)

    op.create_table(
        "crawl_states",
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("checkpoint_value", sa.String(length=255), nullable=True),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("last_modified", sa.String(length=255), nullable=True),
        sa.Column("last_seen_external_id", sa.String(length=255), nullable=True),
        sa.Column("source_version", sa.String(length=64), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["crawl_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", name="uq_crawl_state_source_id"),
    )
    op.create_index(op.f("ix_crawl_states_source_id"), "crawl_states", ["source_id"], unique=False)

    op.create_table(
        "crawl_jobs",
        sa.Column("source_id", sa.String(length=36), nullable=True),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("job_type", crawl_job_type, nullable=False),
        sa.Column("status", crawl_job_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_seen", sa.Integer(), nullable=False),
        sa.Column("records_created", sa.Integer(), nullable=False),
        sa.Column("records_updated", sa.Integer(), nullable=False),
        sa.Column("records_deduped", sa.Integer(), nullable=False),
        sa.Column("records_indexed", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("job_metadata", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["crawl_sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_crawl_jobs_requested_by_user_id"), "crawl_jobs", ["requested_by_user_id"], unique=False)
    op.create_index(op.f("ix_crawl_jobs_source_id"), "crawl_jobs", ["source_id"], unique=False)
    op.create_index(op.f("ix_crawl_jobs_status"), "crawl_jobs", ["status"], unique=False)

    op.create_table(
        "raw_source_snapshots",
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("snapshot_type", sa.String(length=64), nullable=False),
        sa.Column("request_url", sa.String(length=1000), nullable=True),
        sa.Column("normalized_url_hash", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("payload_text", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["crawl_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "external_id", "content_hash", name="uq_raw_snapshot_source_external_content"),
    )
    for column in ("source_id", "external_id", "normalized_url_hash", "content_hash"):
        op.create_index(op.f(f"ix_raw_source_snapshots_{column}"), "raw_source_snapshots", [column], unique=False)

    op.create_table(
        "venues",
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("canonical_title", sa.String(length=500), nullable=False),
        sa.Column("venue_type", venue_type, nullable=False),
        sa.Column("publisher", sa.String(length=255), nullable=True),
        sa.Column("issn_print", sa.String(length=32), nullable=True),
        sa.Column("issn_electronic", sa.String(length=32), nullable=True),
        sa.Column("homepage_url", sa.String(length=1000), nullable=True),
        sa.Column("aims_scope", sa.Text(), nullable=True),
        sa.Column("country", sa.String(length=128), nullable=True),
        sa.Column("language", sa.String(length=64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("indexed_scopus", sa.Boolean(), nullable=False),
        sa.Column("indexed_wos", sa.Boolean(), nullable=False),
        sa.Column("is_open_access", sa.Boolean(), nullable=False),
        sa.Column("is_hybrid", sa.Boolean(), nullable=False),
        sa.Column("avg_review_weeks", sa.Integer(), nullable=True),
        sa.Column("acceptance_rate", sa.Float(), nullable=True),
        sa.Column("apc_usd_min", sa.Float(), nullable=True),
        sa.Column("apc_usd_max", sa.Float(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("title", "canonical_title", "venue_type", "publisher", "issn_print", "issn_electronic"):
        op.create_index(op.f(f"ix_venues_{column}"), "venues", [column], unique=False)

    op.create_table(
        "venue_aliases",
        sa.Column("venue_id", sa.String(length=36), nullable=False),
        sa.Column("alias", sa.String(length=500), nullable=False),
        sa.Column("alias_normalized", sa.String(length=500), nullable=False),
        sa.Column("alias_type", sa.String(length=64), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("venue_id", "alias_normalized", name="uq_venue_alias_normalized"),
    )
    op.create_index(op.f("ix_venue_aliases_alias_normalized"), "venue_aliases", ["alias_normalized"], unique=False)
    op.create_index(op.f("ix_venue_aliases_venue_id"), "venue_aliases", ["venue_id"], unique=False)

    op.create_table(
        "venue_metrics",
        sa.Column("venue_id", sa.String(length=36), nullable=False),
        sa.Column("metric_year", sa.Integer(), nullable=True),
        sa.Column("sjr_quartile", sa.String(length=8), nullable=True),
        sa.Column("jcr_quartile", sa.String(length=8), nullable=True),
        sa.Column("citescore", sa.Float(), nullable=True),
        sa.Column("impact_factor", sa.Float(), nullable=True),
        sa.Column("h_index", sa.Integer(), nullable=True),
        sa.Column("acceptance_rate", sa.Float(), nullable=True),
        sa.Column("avg_review_weeks", sa.Integer(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("venue_id", "metric_year", name="uq_venue_metric_year"),
    )
    op.create_index(op.f("ix_venue_metrics_metric_year"), "venue_metrics", ["metric_year"], unique=False)
    op.create_index(op.f("ix_venue_metrics_venue_id"), "venue_metrics", ["venue_id"], unique=False)

    op.create_table(
        "venue_subjects",
        sa.Column("venue_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("scheme", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("venue_id", "label", name="uq_venue_subject"),
    )
    op.create_index(op.f("ix_venue_subjects_label"), "venue_subjects", ["label"], unique=False)
    op.create_index(op.f("ix_venue_subjects_venue_id"), "venue_subjects", ["venue_id"], unique=False)

    op.create_table(
        "venue_policies",
        sa.Column("venue_id", sa.String(length=36), nullable=False),
        sa.Column("peer_review_model", sa.String(length=64), nullable=True),
        sa.Column("open_access_policy", sa.String(length=255), nullable=True),
        sa.Column("copyright_policy", sa.String(length=255), nullable=True),
        sa.Column("archiving_policy", sa.String(length=255), nullable=True),
        sa.Column("apc_usd", sa.Float(), nullable=True),
        sa.Column("turnaround_weeks", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("venue_id", name="uq_venue_policy_venue"),
    )
    op.create_index(op.f("ix_venue_policies_venue_id"), "venue_policies", ["venue_id"], unique=False)

    op.create_table(
        "articles",
        sa.Column("venue_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("publisher", sa.String(length=255), nullable=True),
        sa.Column("indexed_scopus", sa.Boolean(), nullable=False),
        sa.Column("indexed_wos", sa.Boolean(), nullable=False),
        sa.Column("is_retracted", sa.Boolean(), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=True),
        sa.Column("source_external_id", sa.String(length=255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("venue_id", "title", "doi", "publication_year", "source_external_id"):
        op.create_index(op.f(f"ix_articles_{column}"), "articles", [column], unique=False)

    op.create_table(
        "article_authors",
        sa.Column("article_id", sa.String(length=36), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("affiliation", sa.String(length=500), nullable=True),
        sa.Column("orcid", sa.String(length=64), nullable=True),
        sa.Column("author_order", sa.Integer(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_article_authors_article_id"), "article_authors", ["article_id"], unique=False)
    op.create_index(op.f("ix_article_authors_orcid"), "article_authors", ["orcid"], unique=False)

    op.create_table(
        "article_keywords",
        sa.Column("article_id", sa.String(length=36), nullable=False),
        sa.Column("keyword", sa.String(length=255), nullable=False),
        sa.Column("normalized_keyword", sa.String(length=255), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", "normalized_keyword", name="uq_article_keyword_normalized"),
    )
    op.create_index(op.f("ix_article_keywords_article_id"), "article_keywords", ["article_id"], unique=False)
    op.create_index(op.f("ix_article_keywords_normalized_keyword"), "article_keywords", ["normalized_keyword"], unique=False)

    op.create_table(
        "cfp_events",
        sa.Column("venue_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("topic_tags", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("abstract_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("full_paper_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mode", sa.String(length=64), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("source_name", sa.String(length=64), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("publisher", sa.String(length=255), nullable=True),
        sa.Column("indexed_scopus", sa.Boolean(), nullable=False),
        sa.Column("indexed_wos", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cfp_events_title"), "cfp_events", ["title"], unique=False)
    op.create_index(op.f("ix_cfp_events_venue_id"), "cfp_events", ["venue_id"], unique=False)

    op.create_table(
        "manuscripts",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("file_attachment_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=1000), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("keywords_json", sa.JSON(), nullable=True),
        sa.Column("references_json", sa.JSON(), nullable=True),
        sa.Column("parsed_structure", sa.JSON(), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["file_attachment_id"], ["file_attachments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "session_id", "file_attachment_id"):
        op.create_index(op.f(f"ix_manuscripts_{column}"), "manuscripts", [column], unique=False)

    op.create_table(
        "match_requests",
        sa.Column("manuscript_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("desired_venue_type", sa.String(length=64), nullable=True),
        sa.Column("min_quartile", sa.String(length=8), nullable=True),
        sa.Column("require_scopus", sa.Boolean(), nullable=False),
        sa.Column("require_wos", sa.Boolean(), nullable=False),
        sa.Column("apc_budget_usd", sa.Float(), nullable=True),
        sa.Column("max_review_weeks", sa.Float(), nullable=True),
        sa.Column("include_cfps", sa.Boolean(), nullable=False),
        sa.Column("status", match_request_status, nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=True),
        sa.Column("retrieval_diagnostics", sa.JSON(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["manuscript_id"], ["manuscripts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_match_requests_manuscript_id"), "match_requests", ["manuscript_id"], unique=False)
    op.create_index(op.f("ix_match_requests_user_id"), "match_requests", ["user_id"], unique=False)
    op.create_index(op.f("ix_match_requests_status"), "match_requests", ["status"], unique=False)

    op.create_table(
        "match_candidates",
        sa.Column("match_request_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("venue_id", sa.String(length=36), nullable=True),
        sa.Column("cfp_event_id", sa.String(length=36), nullable=True),
        sa.Column("article_id", sa.String(length=36), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("retrieval_score", sa.Float(), nullable=False),
        sa.Column("scope_overlap_score", sa.Float(), nullable=False),
        sa.Column("quality_fit_score", sa.Float(), nullable=False),
        sa.Column("policy_fit_score", sa.Float(), nullable=False),
        sa.Column("freshness_score", sa.Float(), nullable=False),
        sa.Column("manuscript_readiness_score", sa.Float(), nullable=False),
        sa.Column("penalty_score", sa.Float(), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("explanation_payload", sa.JSON(), nullable=True),
        sa.Column("evidence_payload", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cfp_event_id"], ["cfp_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["match_request_id"], ["match_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("match_request_id", "venue_id", "cfp_event_id", "article_id"):
        op.create_index(op.f(f"ix_match_candidates_{column}"), "match_candidates", [column], unique=False)

    op.create_table(
        "manuscript_assessments",
        sa.Column("manuscript_id", sa.String(length=36), nullable=False),
        sa.Column("readiness_score", sa.Float(), nullable=False),
        sa.Column("title_present", sa.Boolean(), nullable=False),
        sa.Column("abstract_present", sa.Boolean(), nullable=False),
        sa.Column("keyword_count", sa.Integer(), nullable=False),
        sa.Column("reference_count", sa.Integer(), nullable=False),
        sa.Column("estimated_word_count", sa.Integer(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["manuscript_id"], ["manuscripts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manuscript_id", name="uq_manuscript_assessment_manuscript"),
    )
    op.create_index(op.f("ix_manuscript_assessments_manuscript_id"), "manuscript_assessments", ["manuscript_id"], unique=False)

    op.create_table(
        "entity_fingerprints",
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=True),
        sa.Column("normalized_url_hash", sa.String(length=64), nullable=True),
        sa.Column("business_key", sa.String(length=255), nullable=True),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("raw_identifier", sa.String(length=255), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type", "entity_id", "source_name", name="uq_entity_fingerprint_entity_source"),
    )
    for column in ("entity_type", "entity_id", "source_name", "normalized_url_hash", "business_key", "content_fingerprint", "raw_identifier"):
        op.create_index(op.f(f"ix_entity_fingerprints_{column}"), "entity_fingerprints", [column], unique=False)


def downgrade() -> None:
    for table in (
        "entity_fingerprints",
        "manuscript_assessments",
        "match_candidates",
        "match_requests",
        "manuscripts",
        "cfp_events",
        "article_keywords",
        "article_authors",
        "articles",
        "venue_policies",
        "venue_subjects",
        "venue_metrics",
        "venue_aliases",
        "venues",
        "raw_source_snapshots",
        "crawl_jobs",
        "crawl_states",
        "crawl_sources",
    ):
        op.drop_table(table)

    match_request_status.drop(op.get_bind(), checkfirst=True)
    venue_type.drop(op.get_bind(), checkfirst=True)
    crawl_job_type.drop(op.get_bind(), checkfirst=True)
    crawl_job_status.drop(op.get_bind(), checkfirst=True)
