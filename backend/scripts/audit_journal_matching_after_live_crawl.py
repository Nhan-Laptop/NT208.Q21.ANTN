from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal
from app.models.article import Article
from app.models.cfp_event import CFPEvent
from app.models.entity_fingerprint import EntityFingerprint
from app.models.match_request import MatchRequest
from app.models.venue import Venue
from app.models.venue_metric import VenueMetric
from app.models.venue_subject import VenueSubject
from app.services.ingestion.index_service import academic_index_service
from app.services.journal_match.filters import match_filters
from app.services.journal_match.reranker import match_reranker
from app.services.journal_match.service import journal_match_service


QUERIES = {
    "A": "firewall misconfiguration exposed host service network security",
    "B": "cybersecurity intrusion detection network exposure",
    "C": "medical data governance health policy",
    "D": "publishing analytics responsible AI",
}


def _csv(values: list[Any]) -> str:
    return ", ".join(str(value) for value in values if value not in (None, ""))


def _venue_rows(db) -> tuple[list[dict[str, Any]], Counter[str]]:
    rows: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    for venue in db.query(Venue).order_by(Venue.title.asc()).all():
        details = journal_match_service._venue_source_details(db, venue.id)
        eligible, eligibility_reasons = journal_match_service._production_eligibility(
            venue=venue,
            source_details=details,
        )
        reasons.update(eligibility_reasons or ["eligible"])
        subjects = [row[0] for row in db.query(VenueSubject.label).filter(VenueSubject.venue_id == venue.id).all()]
        sources = [detail.get("source_name") for detail in details]
        metrics = [
            f"{metric.source_id or 'unknown'}:{metric.metric_name or 'metric'}={metric.metric_text or metric.metric_value}"
            for metric in db.query(VenueMetric).filter(VenueMetric.venue_id == venue.id).all()
        ]
        rows.append(
            {
                "id": venue.id,
                "title": venue.title,
                "venue_type": venue.venue_type.value,
                "publisher": venue.publisher,
                "official_url": venue.homepage_url,
                "aims_scope": venue.aims_scope,
                "issn": venue.issn_print,
                "eissn": venue.issn_electronic,
                "subjects": subjects,
                "sources": sources,
                "source_types": [detail.get("source_type") for detail in details],
                "trust_tiers": [detail.get("trust_tier") for detail in details],
                "snapshot_hashes": [hash_value for detail in details for hash_value in detail.get("snapshot_hashes", [])],
                "metrics": metrics,
                "production_eligible": eligible,
                "exclusion_reasons": eligibility_reasons,
            }
        )
    return rows, reasons


def _entity_count_table(db, venue_rows: list[dict[str, Any]]) -> list[tuple[str, int, int, int, str]]:
    eligible = sum(1 for row in venue_rows if row["production_eligible"])
    excluded = len(venue_rows) - eligible
    seed_demo_internal = sum(
        1
        for row in venue_rows
        if any(
            "internal_source" in reason or "synthetic_" in reason
            for reason in row["exclusion_reasons"]
        )
    )
    official_url = sum(1 for row in venue_rows if row["official_url"])
    issn = sum(1 for row in venue_rows if row["issn"] or row["eissn"])
    scopus = sum(1 for row in venue_rows if "scopus" in row["sources"])
    usable_subject = sum(1 for row in venue_rows if row["subjects"] or row["aims_scope"])
    security_terms = {"computer", "computing", "cybersecurity", "security", "network", "networks", "communications"}
    security = sum(
        1
        for row in venue_rows
        if security_terms
        & set(
            " ".join(
                [
                    row["title"] or "",
                    row["publisher"] or "",
                    " ".join(row["subjects"]),
                ]
            )
            .lower()
            .replace("/", " ")
            .split()
        )
    )
    return [
        ("venues", len(venue_rows), eligible, excluded, "see venue exclusion reason table"),
        ("articles", db.query(Article).count(), 0, db.query(Article).count(), "not primary journal candidates"),
        ("cfps", db.query(CFPEvent).count(), 0, db.query(CFPEvent).count(), "evidence only; not primary journal candidates"),
        ("venue_seed_demo_internal", seed_demo_internal, 0, seed_demo_internal, "internal/synthetic provenance"),
        ("venue_with_official_url", official_url, official_url, len(venue_rows) - official_url, "missing homepage_url"),
        ("venue_with_issn_or_eissn", issn, issn, len(venue_rows) - issn, "missing ISSN/eISSN"),
        ("venue_with_scopus_provenance", scopus, scopus, len(venue_rows) - scopus, "missing scopus provenance"),
        ("venue_with_usable_subject_domain", usable_subject, usable_subject, len(venue_rows) - usable_subject, "missing subject/domain text"),
        ("venue_computer_science_security", security, security, len(venue_rows) - security, "no CS/security terms"),
    ]


def _audit_query(db, label: str, query: str) -> dict[str, Any]:
    retrieved = academic_index_service.query_all(query_text=query, top_k_each=5)
    request = MatchRequest(
        manuscript_id="audit",
        user_id="audit",
        desired_venue_type="journal",
        include_cfps=False,
    )
    filtered, diagnostics = match_filters.apply(request, retrieved)
    finalized, final_diagnostics = journal_match_service._finalize_primary_candidates(
        db,
        request=request,
        manuscript_text=query,
        candidates=filtered,
    )
    ranked = match_reranker.rerank(
        request=request,
        manuscript_text=query,
        readiness_score=0.5,
        candidates=finalized,
    )
    return {
        "label": label,
        "query": query,
        "status": "matched" if ranked else "insufficient_evidence",
        "collections": Counter(row.get("collection") for row in retrieved),
        "raw_top": [
            {
                "collection": row.get("collection"),
                "title": row.get("metadata", {}).get("title") or row.get("metadata", {}).get("venue_title") or row.get("record_id"),
                "score": round(float(row.get("retrieval_score") or 0.0), 4),
            }
            for row in retrieved[:5]
        ],
        "final_top": [
            {
                "title": row.get("metadata", {}).get("primary_label") or row.get("metadata", {}).get("title"),
                "score": row.get("final_score"),
                "domain_fit": row.get("score_breakdown", {}).get("domain_fit_score"),
                "sources": row.get("metadata", {}).get("provenance_sources"),
                "trust_tiers": row.get("metadata", {}).get("trust_tiers"),
            }
            for row in ranked[:5]
        ],
        "rejected": final_diagnostics.get("finalization", {}).get("rejected", []),
        "filter_rejected": diagnostics.get("rejected", []),
    }


def main() -> None:
    db = SessionLocal()
    try:
        venue_rows, reason_counts = _venue_rows(db)
        counts = academic_index_service.collection_counts()

        print("# Journal Matching Live Crawl Audit")
        print()
        print("## Entity Counts")
        print("| entity_count | production_eligible_count | excluded_count | exclusion_reasons |")
        print("|---|---:|---:|---|")
        for name, total, eligible, excluded, reason in _entity_count_table(db, venue_rows):
            print(f"| {name}: {total} | {eligible} | {excluded} | {reason} |")
        print()
        print("## Venue Exclusion Reasons")
        print("| reason | count |")
        print("|---|---:|")
        for reason, count in sorted(reason_counts.items()):
            print(f"| {reason} | {count} |")
        print()
        print("## Sample Venues")
        print("| title | domain/subjects | ISSN/eISSN | publisher | metrics | sources | trust_tier | snapshot_hashes |")
        print("|---|---|---|---|---|---|---|---|")
        for row in venue_rows[:12]:
            print(
                "| "
                + " | ".join(
                    [
                        str(row["title"]),
                        _csv(row["subjects"]),
                        _csv([row["issn"], row["eissn"]]),
                        str(row["publisher"] or ""),
                        _csv(row["metrics"]),
                        _csv(row["sources"]),
                        _csv(row["trust_tiers"]),
                        _csv(row["snapshot_hashes"][:2]),
                    ]
                )
                + " |"
            )
        print()
        print("## Chroma Collections")
        print("| collection | count |")
        print("|---|---:|")
        for name in ("venue_profiles", "cfp_notices", "article_exemplars"):
            print(f"| {name} | {counts.get(name, 0)} |")
        print()
        print("## Retrieval Audit")
        print("| query | status | raw_top | final_top |")
        print("|---|---|---|---|")
        for label, query in QUERIES.items():
            audit = _audit_query(db, label, query)
            raw_top = "; ".join(f"{item['collection']}:{item['title']} ({item['score']})" for item in audit["raw_top"])
            final_top = "; ".join(f"{item['title']} ({item['score']})" for item in audit["final_top"]) or "none"
            print(f"| {label} | {audit['status']} | {raw_top} | {final_top} |")
    finally:
        db.close()


if __name__ == "__main__":
    main()
