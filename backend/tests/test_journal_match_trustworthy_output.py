from __future__ import annotations

import sys
import unittest
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.article import Article
from app.models.cfp_event import CFPEvent
from app.models.entity_fingerprint import EntityFingerprint
from app.models.match_request import MatchRequest
from app.models.chat_message import MessageRole, MessageType
from app.models.chat_session import SessionMode
from app.models.venue import Venue
from app.models.venue_subject import VenueSubject
from app.models.academic_common import VenueType
from app.schemas.academic import MatchRequestCreate
from app.services.chat_service import chat_service
from app.services.ingestion.index_service import academic_index_service
from app.services.journal_match.reranker import match_reranker
from app.services.journal_match.topic_profile import ManuscriptTopicProfile
from app.services.academic_policy import format_journal_match_summary
from app.services.journal_match.service import build_legacy_journal_payload, build_legacy_journal_rows, journal_match_service
from crawler.scheduler import crawl_scheduler

try:
    from .support import SAMPLE_MANUSCRIPT, TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import SAMPLE_MANUSCRIPT, TestEnvironment


class TrustworthyJournalMatchOutputTest(unittest.TestCase):
    CRYPTOGRAPHY_ABSTRACT = (
        "We propose a general polynomial time algorithm to find small integer solutions to systems of linear "
        "congruences. We use this algorithm to obtain two polynomial time algorithms for reconstructing the "
        "values of variables x1,...,xk when we are given some linear congruences relating them together with "
        "some bits obtained by truncating the binary expansions of the variables. The first algorithm "
        "reconstructs the variables when either the high order bits or the low order bits of the x are known. "
        "The second algorithm reconstructs the variables when an arbitrary window of consecutive bits of the "
        "variables is known. Two cryptanalytic applications of the algorithms are given: predicting linear "
        "congruential generators..."
    )

    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()
        self.session = self.env.create_chat_session(user=self.user)
        with self.env.session() as db:
            crawl_scheduler.run_crawl_job(db, current_user=self.user, include_live_sources=False)

    def tearDown(self) -> None:
        self.env.close()

    def _indexed_candidate(self, *, record_id: str, collection: str, document: str, metadata: dict, score: float) -> dict:
        return {
            "record_id": record_id,
            "collection": collection,
            "document": document,
            "metadata": metadata,
            "retrieval_score": score,
        }

    def _create_production_security_venue(self, db) -> Venue:
        venue = Venue(
            title="Journal of Network Security Operations",
            canonical_title="Journal of Network Security Operations",
            venue_type=VenueType.JOURNAL,
            publisher="Trusted Security Society",
            homepage_url="https://security.example.org/jnso",
            aims_scope="Publishes network security, firewall hardening, exposed service analysis, intrusion detection, and attack surface management research.",
            indexed_scopus=True,
            indexed_wos=False,
            is_open_access=False,
            is_hybrid=True,
        )
        db.add(venue)
        db.flush()
        db.add(VenueSubject(venue_id=venue.id, label="Network Security", source="trusted-index", scheme="keyword"))
        db.add(VenueSubject(venue_id=venue.id, label="Cybersecurity", source="trusted-index", scheme="keyword"))
        db.add(
            EntityFingerprint(
                entity_type="venue",
                entity_id=venue.id,
                source_name="trusted-index",
                raw_identifier=venue.canonical_title,
                business_key="trusted-security-society|journal-of-network-security-operations",
            )
        )
        db.flush()
        return venue

    def test_journal_only_output_demotes_article_cfp_and_conference_records(self) -> None:
        with self.env.session() as db:
            journal = self._create_production_security_venue(db)
            conference = db.query(Venue).filter(Venue.title == "International Conference on Scientific Knowledge Graphs").one()
            article = Article(
                venue_id=journal.id,
                title="Firewall Misconfiguration Detection in Exposed Services",
                abstract="Network security controls for firewall misconfiguration, packet filtering, and exposed services.",
                doi="10.5555/jnso.2026.001",
                publication_year=2026,
                publisher="Trusted Security Society",
                source_name="trusted-index",
                source_external_id="jnso-001",
            )
            cfp = CFPEvent(
                venue_id=journal.id,
                title="Special Issue on Firewall Hardening",
                description="Network security submissions on exposed service risk and firewall hardening.",
                topic_tags=["network security", "firewall", "attack surface"],
                status="open",
                full_paper_deadline=datetime.now(timezone.utc) + timedelta(days=90),
                source_name="trusted-index",
                source_url="https://security.example.org/jnso/cfp",
            )
            db.add_all([article, cfp])
            db.flush()

            journal_doc, journal_meta = academic_index_service.build_venue_document(journal)
            conf_doc, conf_meta = academic_index_service.build_venue_document(conference)
            article_doc, article_meta = academic_index_service.build_article_document(article)
            cfp_doc, cfp_meta = academic_index_service.build_cfp_document(cfp)
            retrieved = [
                self._indexed_candidate(record_id=f"article:{article.id}", collection="article_exemplars", document=article_doc, metadata=article_meta, score=0.99),
                self._indexed_candidate(record_id=f"cfp:{cfp.id}", collection="cfp_notices", document=cfp_doc, metadata=cfp_meta, score=0.98),
                self._indexed_candidate(record_id=f"venue:{conference.id}", collection="venue_profiles", document=conf_doc, metadata=conf_meta, score=0.97),
                self._indexed_candidate(record_id=f"venue:{journal.id}", collection="venue_profiles", document=journal_doc, metadata=journal_meta, score=0.40),
            ]

            request = journal_match_service.create_match_request(
                db,
                current_user=self.user,
                payload=MatchRequestCreate(
                    session_id=self.session.id,
                    text="Firewall misconfiguration and network security controls for exposed services and attack surface hardening.",
                    desired_venue_type="journal",
                    include_cfps=False,
                    top_k=5,
                ),
            )
            with patch("app.services.journal_match.service.manuscript_retriever.retrieve", return_value=retrieved):
                journal_match_service.run_request(db, current_user=self.user, request_id=request.id)
            result = journal_match_service.get_result(db, current_user=self.user, request_id=request.id)
            rows, summary = build_legacy_journal_payload(result)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["journal"], "Journal of Network Security Operations")
            self.assertEqual(rows[0]["entity_type"], "venue")
            self.assertEqual(rows[0]["venue_type"], "journal")
            self.assertNotEqual(rows[0]["journal"], article.title)
            self.assertNotIn("Conference", rows[0]["journal"])
            self.assertIsNone(rows[0]["deadline"])
            self.assertEqual(result["candidates"][0].entity_type, "venue")
            evidence_titles = [item["title"] for item in rows[0]["supporting_evidence"]]
            self.assertIn(article.title, evidence_titles)
            self.assertNotIn(article.title, [row["journal"] for row in rows])
            self.assertIn("một danh sách gợi ý journal duy nhất", summary)

    def test_security_query_excludes_internal_demo_seed_venues(self) -> None:
        with self.env.session() as db:
            request = journal_match_service.create_match_request(
                db,
                current_user=self.user,
                payload=MatchRequestCreate(
                    session_id=self.session.id,
                    text="Firewall misconfiguration, exposed hosts and network security hardening for public services.",
                    desired_venue_type="journal",
                    include_cfps=False,
                    top_k=5,
                ),
            )
            journal_match_service.run_request(db, current_user=self.user, request_id=request.id)
            result = journal_match_service.get_result(db, current_user=self.user, request_id=request.id)
            rows, summary = build_legacy_journal_payload(result)

            blocked = {
                "Journal of Health Data Governance",
                "Journal of Responsible AI Systems",
                "Journal of Computational Publishing Analytics",
                "Computational Social Science Methods Review",
            }
            self.assertEqual([row["journal"] for row in rows if row["journal"] in blocked], [])
            self.assertEqual(result["request"].retrieval_diagnostics["match_status"], "insufficient_corpus")
            self.assertIn("corpus học thuật đã xác minh", summary.lower())
            self.assertTrue(
                any(
                    "not_production_eligible" in rejected.get("reasons", [])
                    for rejected in result["request"].retrieval_diagnostics["finalization"]["rejected"]
                )
            )

    def test_production_seed_file_is_empty_and_fixture_titles_do_not_surface(self) -> None:
        production_seed = json.loads((BACKEND_ROOT / "data" / "academic_seed.json").read_text(encoding="utf-8"))
        self.assertEqual(production_seed, {"venues": [], "articles": [], "cfp_events": []})

        fixture_seed = json.loads((BACKEND_ROOT / "tests" / "fixtures" / "academic_seed.json").read_text(encoding="utf-8"))
        fixture_titles = {item["title"] for item in fixture_seed["venues"]}
        with self.env.session() as db:
            request = journal_match_service.create_match_request(
                db,
                current_user=self.user,
                payload=MatchRequestCreate(
                    session_id=self.session.id,
                    text="Firewall misconfiguration exposed hosts network security validation model.",
                    desired_venue_type="journal",
                    include_cfps=False,
                    top_k=5,
                ),
            )
            journal_match_service.run_request(db, current_user=self.user, request_id=request.id)
            result = journal_match_service.get_result(db, current_user=self.user, request_id=request.id)
            rows, _summary = build_legacy_journal_payload(result)

        self.assertFalse(fixture_titles & {row["journal"] for row in rows})

    def test_scopus_venue_without_domain_scope_does_not_overrank_security_query(self) -> None:
        with self.env.session() as db:
            venue = Venue(
                title="[Rinsho ketsueki] The Japanese journal of clinical hematology",
                canonical_title="[Rinsho ketsueki] The Japanese journal of clinical hematology",
                venue_type=VenueType.JOURNAL,
                issn_print="04851439",
                issn_electronic="18820824",
                indexed_scopus=True,
            )
            db.add(venue)
            db.flush()
            db.add(
                EntityFingerprint(
                    entity_type="venue",
                    entity_id=venue.id,
                    source_name="scopus",
                    raw_identifier=venue.canonical_title,
                    business_key="04851439",
                    content_fingerprint="scopus-smoke-row",
                )
            )
            db.flush()
            document, metadata = academic_index_service.build_venue_document(venue)
            retrieved = [
                self._indexed_candidate(
                    record_id=f"venue:{venue.id}",
                    collection="venue_profiles",
                    document=document,
                    metadata=metadata,
                    score=0.99,
                )
            ]
            request = journal_match_service.create_match_request(
                db,
                current_user=self.user,
                payload=MatchRequestCreate(
                    session_id=self.session.id,
                    text="Firewall misconfiguration exposed hosts and network security model validation.",
                    desired_venue_type="journal",
                    include_cfps=False,
                    top_k=5,
                ),
            )
            with patch("app.services.journal_match.service.manuscript_retriever.retrieve", return_value=retrieved):
                journal_match_service.run_request(db, current_user=self.user, request_id=request.id)
            result = journal_match_service.get_result(db, current_user=self.user, request_id=request.id)
            rows, summary = build_legacy_journal_payload(result)

        self.assertEqual(rows, [])
        self.assertEqual(result["request"].retrieval_diagnostics["match_status"], "insufficient_corpus")
        self.assertIn("corpus học thuật đã xác minh", summary.lower())

    def test_cryptography_query_rejects_biomedical_and_invalid_venues_without_filling_top_k(self) -> None:
        with self.env.session() as db:
            bad_specs = [
                (
                    "Nihon Kyobu Geka Gakkai zasshi",
                    "Japanese journal of thoracic surgery and clinical medicine.",
                    "Surgery",
                ),
                (
                    "Rinsho ketsueki",
                    "Japanese journal of clinical hematology and patient medicine.",
                    "Clinical Medicine; Hematology",
                ),
                (
                    "@GRH",
                    "A malformed alias-style venue title that must not be production eligible.",
                    "Algorithms",
                ),
            ]
            retrieved = []
            for title, scope, subject in bad_specs:
                venue = Venue(
                    title=title,
                    canonical_title=title,
                    venue_type=VenueType.JOURNAL,
                    publisher="Trusted Index Publisher",
                    aims_scope=scope,
                    indexed_scopus=True,
                )
                db.add(venue)
                db.flush()
                for label in subject.split(";"):
                    db.add(VenueSubject(venue_id=venue.id, label=label.strip(), source="scopus", scheme="subject"))
                db.add(
                    EntityFingerprint(
                        entity_type="venue",
                        entity_id=venue.id,
                        source_name="scopus",
                        raw_identifier=venue.canonical_title,
                        business_key=f"scopus|{venue.id}",
                    )
                )
                db.flush()
                document, metadata = academic_index_service.build_venue_document(venue)
                retrieved.append(
                    self._indexed_candidate(
                        record_id=f"venue:{venue.id}",
                        collection="venue_profiles",
                        document=document,
                        metadata=metadata,
                        score=0.99,
                    )
                )

            request = journal_match_service.create_match_request(
                db,
                current_user=self.user,
                payload=MatchRequestCreate(
                    session_id=self.session.id,
                    text=self.CRYPTOGRAPHY_ABSTRACT,
                    desired_venue_type="journal",
                    include_cfps=False,
                    top_k=3,
                ),
            )
            with patch("app.services.journal_match.service.manuscript_retriever.retrieve", return_value=retrieved):
                journal_match_service.run_request(db, current_user=self.user, request_id=request.id)
            result = journal_match_service.get_result(db, current_user=self.user, request_id=request.id)
            rows, summary = build_legacy_journal_payload(result)

        self.assertEqual(rows, [])
        diagnostics = result["request"].retrieval_diagnostics
        self.assertEqual(diagnostics["match_status"], "insufficient_corpus")
        self.assertIn("computer science", diagnostics["detected_domain"])
        self.assertIn("cryptography", diagnostics["detected_domain"])
        # User provided full abstract → summary must NOT ask to supplement abstract
        self.assertNotIn("hãy bổ sung", summary.lower())
        self.assertNotIn("bổ sung abstract", summary.lower())
        # Status must be insufficient_corpus (not missing_manuscript_info)
        self.assertTrue(diagnostics.get("insufficient_corpus"))
        self.assertFalse(diagnostics.get("missing_manuscript_info"))
        payload_text = json.dumps({"rows": rows, "summary": summary}, ensure_ascii=False).lower()
        for blocked in ("@grh", "nihon kyobu geka gakkai", "rinsho ketsueki", "hematology", "surgery", "clinical medicine"):
            self.assertNotIn(blocked, payload_text)
        rejected_reasons = [
            reason
            for rejected in diagnostics["finalization"]["rejected"]
            for reason in rejected.get("reasons", [])
        ]
        self.assertTrue(
            "hard_domain_mismatch" in rejected_reasons or "subject_area_mismatch" in rejected_reasons,
            msg=f"Expected hard_domain_mismatch or subject_area_mismatch, got {rejected_reasons}",
        )
        self.assertTrue(
            "invalid_venue_title" in rejected_reasons or "subject_area_mismatch" in rejected_reasons,
            msg=f"Expected invalid_venue_title or subject_area_mismatch, got {rejected_reasons}",
        )

    def test_short_abstract_marks_missing_manuscript_info(self) -> None:
        """A minimal input with no real content should be missing_manuscript_info,
        not insufficient_corpus."""
        with self.env.session() as db:
            request = journal_match_service.create_match_request(
                db,
                current_user=self.user,
                payload=MatchRequestCreate(
                    session_id=self.session.id,
                    text="I need a journal recommendation for my paper.",
                    desired_venue_type="journal",
                    include_cfps=False,
                    top_k=3,
                ),
            )
            journal_match_service.run_request(db, current_user=self.user, request_id=request.id)
            result = journal_match_service.get_result(db, current_user=self.user, request_id=request.id)
            diagnostics = result["request"].retrieval_diagnostics
            summary = format_journal_match_summary(
                status=result["request"].status,
                candidate_count=0,
                diagnostics=diagnostics,
            )

        self.assertEqual(diagnostics["match_status"], "missing_manuscript_info")
        self.assertTrue(diagnostics.get("missing_manuscript_info"))
        self.assertFalse(diagnostics.get("insufficient_corpus"))
        self.assertIn("hãy bổ sung", summary.lower())
        self.assertEqual(result["request"].status.value, "succeeded")

    def test_unsupported_metrics_are_hidden_without_metric_provenance(self) -> None:
        candidate = SimpleNamespace(
            entity_type="venue",
            final_score=0.72,
            evidence_payload={
                "metadata": {
                    "title": "Journal Without Provenance",
                    "venue_id": "venue-1",
                    "venue_type": "journal",
                    "impact_factor": 9.9,
                    "h_index": 100,
                    "avg_review_weeks": 4,
                    "acceptance_rate": 0.1,
                    "is_open_access": True,
                }
            },
            explanation_payload={"summary": "Grounded venue row."},
        )

        rows = build_legacy_journal_rows({"candidates": [candidate]})
        row = rows[0]
        self.assertIsNone(row["impact_factor"])
        self.assertIsNone(row["h_index"])
        self.assertIsNone(row["review_time_weeks"])
        self.assertIsNone(row["acceptance_rate"])
        self.assertFalse(row["open_access"])
        self.assertIn("impact_factor", row["unverified_metrics"])
        self.assertEqual(row["metric_provenance"], {})

    def test_final_payload_has_one_ordered_top_k_source_of_truth(self) -> None:
        with self.env.session() as db:
            request = journal_match_service.create_match_request(
                db,
                current_user=self.user,
                payload=MatchRequestCreate(
                    session_id=self.session.id,
                    text=SAMPLE_MANUSCRIPT,
                    desired_venue_type="journal",
                    include_cfps=False,
                    top_k=3,
                ),
            )
            journal_match_service.run_request(db, current_user=self.user, request_id=request.id)
            result = journal_match_service.get_result(db, current_user=self.user, request_id=request.id)
            rows, _summary = build_legacy_journal_payload(result)
            candidate_names = [
                (candidate.evidence_payload or {}).get("metadata", {}).get("primary_label")
                for candidate in result["candidates"]
            ]
            self.assertEqual([row["journal"] for row in rows], candidate_names)
            self.assertLessEqual(len(rows), 3)


class NetworkSecurityDomainRankingTest(unittest.TestCase):
    def test_reranker_uses_only_verified_metrics_when_provenance_is_present(self) -> None:
        request = MatchRequest(
            manuscript_id="m1",
            user_id="u1",
            desired_venue_type="journal",
            apc_budget_usd=500,
            max_review_weeks=8,
        )
        candidate = {
            "record_id": "venue:unverified-metrics",
            "retrieval_score": 0.7,
            "document": "journal scope scientific retrieval ranking systems",
            "metadata": {
                "entity_type": "venue",
                "venue_type": "journal",
                "title": "Journal With Unverified Metrics",
                "impact_factor": 99.0,
                "citescore": 99.0,
                "indexed_scopus": True,
                "indexed_wos": True,
                "apc_usd": 10,
                "avg_review_weeks": 2,
                "is_open_access": True,
                "verified_metrics": {},
                "metric_provenance": {},
            },
        }

        ranked = match_reranker.rerank(
            request=request,
            manuscript_text="scientific retrieval and transparent ranking systems",
            readiness_score=0.8,
            candidates=[candidate],
        )
        breakdown = ranked[0]["score_breakdown"]

        self.assertEqual(breakdown["quality_fit_score"], 0.35)
        self.assertEqual(breakdown["policy_fit_score"], 0.4)
        self.assertEqual(breakdown["penalty_score"], 0.0)

    def test_firewall_query_penalizes_off_domain_candidates(self) -> None:
        request = MatchRequest(manuscript_id="m1", user_id="u1", desired_venue_type="journal")
        candidates = [
            {
                "record_id": "venue:security",
                "retrieval_score": 0.72,
                "document": "journal scope network security firewall misconfiguration intrusion detection internet systems",
                "metadata": {"entity_type": "venue", "venue_type": "journal", "title": "Journal of Network Security"},
            },
            {
                "record_id": "venue:offdomain",
                "retrieval_score": 0.90,
                "document": "schema evolution continuous integration health governance policy analytics",
                "metadata": {"entity_type": "venue", "venue_type": "journal", "title": "Journal of Health Governance"},
            },
        ]
        ranked = match_reranker.rerank(
            request=request,
            manuscript_text="firewall misconfiguration and network security controls for packet filtering",
            readiness_score=0.8,
            candidates=candidates,
        )
        self.assertEqual(ranked[0]["record_id"], "venue:security")
        off_domain = next(item for item in ranked if item["record_id"] == "venue:offdomain")
        self.assertIn("network_security_mismatch", off_domain["score_breakdown"]["domain_mismatch_reasons"])
        self.assertGreaterEqual(off_domain["score_breakdown"]["penalty_score"], 0.45)


class JournalFollowupReuseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()
        self.session = self.env.create_chat_session(user=self.user, mode=SessionMode.JOURNAL_MATCH)

    def tearDown(self) -> None:
        self.env.close()

    def test_followup_reuses_previous_journal_payload_without_recomputing(self) -> None:
        previous_payload = {
            "type": "journal_list",
            "request_id": "req-123",
            "candidate_ids": ["mc-1"],
            "data": [
                {
                    "candidate_id": "mc-1",
                    "journal": "Journal of Network Security Operations",
                    "venue_id": "venue-sec",
                    "venue_type": "journal",
                    "entity_type": "venue",
                    "score": 0.91,
                    "reason": "Network security and firewall scope match.",
                    "domains": ["Network Security", "Cybersecurity"],
                    "supporting_evidence": [
                        {"title": "Firewall Misconfiguration Detection in Exposed Services", "publication_year": 2026}
                    ],
                }
            ],
        }
        with self.env.session() as db:
            chat_service._save_message(
                db=db,
                session_id=self.session.id,
                role=MessageRole.ASSISTANT,
                content="Previous journal recommendations.",
                message_type=MessageType.JOURNAL_LIST,
                tool_results=previous_payload,
            )

        with patch("app.services.chat_service.journal_match_service.run_request") as run_request:
            with self.env.session() as db:
                _user, assistant, _session = chat_service.complete_chat(
                    db,
                    current_user=self.user,
                    session_id=self.session.id,
                    user_message="giới thiệu về từng journal",
                )

        run_request.assert_not_called()
        self.assertEqual(assistant.message_type, MessageType.JOURNAL_LIST)
        self.assertEqual(assistant.tool_results["data"], previous_payload["data"])
        self.assertEqual(assistant.tool_results["candidate_ids"], previous_payload["candidate_ids"])
        self.assertEqual(assistant.tool_results["source"], "prior_journal_list_followup")
        self.assertIn("không chạy lại ranking mới", assistant.content)


class JournalMatchRegressionTest(unittest.TestCase):
    NUMPY_ABSTRACT = (
        "Array programming with NumPy. NumPy is the fundamental array programming library "
        "for scientific computing in Python. It provides a high-performance multidimensional "
        "array object and tools for working with these arrays. We demonstrate how NumPy enables "
        "efficient numerical computations through vectorization, broadcasting, and indexing. "
        "As an application example, we use NumPy to analyze gravitational wave data from LIGO, "
        "and we apply the library to reconstruct black hole images from the Event Horizon Telescope. "
        "NumPy has become a cornerstone of the Python scientific computing stack."
    )

    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()
        self.session = self.env.create_chat_session(user=self.user)
        with self.env.session() as db:
            crawl_scheduler.run_crawl_job(db, current_user=self.user, include_live_sources=False)

    def tearDown(self) -> None:
        self.env.close()

    def _indexed_candidate(self, *, record_id: str, collection: str, document: str, metadata: dict, score: float) -> dict:
        return {
            "record_id": record_id,
            "collection": collection,
            "document": document,
            "metadata": metadata,
            "retrieval_score": score,
        }

    def _create_venue(
        self, db, *, title: str, scope: str, subjects: list[str], source_name: str = "trusted-index",
        publisher: str = "Trusted Publisher", indexed_scopus: bool = True,
    ):
        venue = Venue(
            title=title, canonical_title=title, venue_type=VenueType.JOURNAL,
            publisher=publisher, aims_scope=scope, indexed_scopus=indexed_scopus,
        )
        db.add(venue)
        db.flush()
        for label in subjects:
            db.add(VenueSubject(venue_id=venue.id, label=label, source=source_name, scheme="keyword"))
        db.add(EntityFingerprint(
            entity_type="venue", entity_id=venue.id, source_name=source_name,
            raw_identifier=venue.canonical_title, business_key=f"{publisher}|{title}",
        ))
        db.flush()
        return venue.id

    def test_numpy_doi_excludes_astronomy_and_social_venues(self) -> None:
        with self.env.session() as db:
            # Create relevant venues
            joss_id = self._create_venue(db, title="Journal of Open Source Software",
                scope="Scientific open source software and programming libraries.",
                subjects=["Computer Science", "Scientific Computing", "Software"])
            acm_toms_id = self._create_venue(db, title="ACM Transactions on Mathematical Software",
                scope="Mathematical software, numerical algorithms, and scientific computing.",
                subjects=["Computer Science", "Numerical Analysis", "Mathematics"])
            # Create bad venues
            astro_id = self._create_venue(db, title="Annual Review of Astronomy and Astrophysics",
                scope="Astronomy and astrophysics research.",
                subjects=["Astronomy", "Astrophysics"])
            bio_id = self._create_venue(db, title="Biography",
                scope="Biographical studies.",
                subjects=["Biography", "Literature"])
            archives_id = self._create_venue(db, title="Archives and Manuscripts",
                scope="Archival science and manuscript studies.",
                subjects=["Archival Science", "History"])

            for vid in [joss_id, acm_toms_id, astro_id, bio_id, archives_id]:
                academic_index_service.upsert_venue(db, vid)

            from app.services.journal_match.topic_profile import ManuscriptTopicProfile
            topic_profile = ManuscriptTopicProfile(
                title="Array programming with NumPy",
                abstract=self.NUMPY_ABSTRACT,
                keywords=["NumPy", "array programming", "scientific computing"],
                subjects=["Computer Science", "Scientific Computing"],
            )
            query_text = topic_profile.build_embedding_query()

            request = journal_match_service.create_match_request(
                db, current_user=self.user,
                payload=MatchRequestCreate(
                    session_id=self.session.id, text=query_text,
                    title="Array programming with NumPy",
                    desired_venue_type="journal", include_cfps=False, top_k=5,
                ),
            )
            with patch("app.services.journal_match.service.manuscript_retriever.retrieve") as mock_retrieve:
                all_retrieved = academic_index_service.query_all(query_text=query_text, top_k_each=10)
                mock_retrieve.return_value = all_retrieved
                journal_match_service.run_request(db, current_user=self.user, request_id=request.id)

            result = journal_match_service.get_result(db, current_user=self.user, request_id=request.id)
            rows, _summary = build_legacy_journal_payload(result)
            journal_titles = [row["journal"] for row in rows]

        # Must include CS/computing venues
        self.assertTrue(
            any("Software" in t or "Mathematical" in t for t in journal_titles),
            msg=f"Expected CS/software venues in results, got {journal_titles}",
        )
        # Must NOT include astronomy, biography, or archives
        blocked = {"Annual Review of Astronomy and Astrophysics", "Biography", "Archives and Manuscripts"}
        for title in journal_titles:
            self.assertNotIn(title, blocked, msg=f"Blocked venue {title} appeared in results")

    def test_street_food_returns_cultural_and_urban_venues(self) -> None:
        with self.env.session() as db:
            food_id = self._create_venue(db, title="Food, Culture & Society",
                scope="Food studies, culinary culture, and food in society.",
                subjects=["Food Studies", "Cultural Studies", "Sociology"])
            urban_id = self._create_venue(db, title="Journal of Urban Culture Research",
                scope="Urban culture, public space, and city life.",
                subjects=["Urban Studies", "Cultural Studies"])
            tourism_id = self._create_venue(db, title="Tourism Geographies",
                scope="Tourism, travel, and destination research.",
                subjects=["Tourism", "Geography"])
            cs_id = self._create_venue(db, title="Journal of Computational Science",
                scope="Computational science and numerical methods.",
                subjects=["Computer Science", "Scientific Computing"])

            retrieved_candidates = []
            for vid in [food_id, urban_id, tourism_id, cs_id]:
                venue = db.query(Venue).filter(Venue.id == vid).first()
                doc, meta = academic_index_service.build_venue_document(venue)
                retrieved_candidates.append(self._indexed_candidate(
                    record_id=f"venue:{vid}", collection="venue_profiles",
                    document=doc, metadata=meta, score=0.85,
                ))

            request = journal_match_service.create_match_request(
                db, current_user=self.user,
                payload=MatchRequestCreate(
                    session_id=self.session.id,
                    text="Traditional Vietnamese street food and urban sidewalk culture.",
                    desired_venue_type="journal", include_cfps=False, top_k=5,
                ),
            )
            with patch("app.services.journal_match.service.manuscript_retriever.retrieve", return_value=retrieved_candidates):
                journal_match_service.run_request(db, current_user=self.user, request_id=request.id)

            result = journal_match_service.get_result(db, current_user=self.user, request_id=request.id)
            rows, _summary = build_legacy_journal_payload(result)
            journal_titles = [row["journal"] for row in rows]

        self.assertTrue(
            any("Food" in t or "Urban" in t or "Tourism" in t for t in journal_titles),
            msg=f"Expected food/urban/tourism venues in results, got {journal_titles}",
        )

    def test_insufficient_matches_does_not_fill_top_k(self) -> None:
        with self.env.session() as db:
            unrelated_id = self._create_venue(db, title="Journal of Unrelated Topics",
                scope="Unrelated research topics with no connection to the query.",
                subjects=["General Science"])

            academic_index_service.upsert_venue(db, unrelated_id)

            from app.services.journal_match.service import journal_match_service
            from app.services.journal_match.filters import match_filters
            from app.services.journal_match.reranker import match_reranker

            request = journal_match_service.create_match_request(
                db, current_user=self.user,
                payload=MatchRequestCreate(
                    session_id=self.session.id,
                    text="Very specific quantum cryptography protocol for post-quantum communications.",
                    desired_venue_type="journal", include_cfps=False, top_k=5,
                ),
            )
            with patch("app.services.journal_match.service.manuscript_retriever.retrieve") as mock_retrieve:
                document, metadata = academic_index_service.build_venue_document(
                    db.query(Venue).filter(Venue.id == unrelated_id).first()
                )
                mock_retrieve.return_value = [{
                    "record_id": f"venue:{unrelated_id}",
                    "collection": "venue_profiles",
                    "document": document,
                    "metadata": metadata,
                    "retrieval_score": 0.15,
                }]
                journal_match_service.run_request(db, current_user=self.user, request_id=request.id)

            result = journal_match_service.get_result(db, current_user=self.user, request_id=request.id)
            diagnostics = result["request"].retrieval_diagnostics
            rows, _summary = build_legacy_journal_payload(result)

        if not rows:
            self.assertEqual(diagnostics["match_status"], "insufficient_corpus")
        else:
            self.assertLessEqual(len(rows), 1,
                                 msg="Should not fill top_k with low-quality candidates")

    def test_subject_compatibility_filter_rejects_wrong_field(self) -> None:
        with self.env.session() as db:
            med_id = self._create_venue(db, title="Japanese Journal of Clinical Hematology",
                scope="Clinical hematology, patient treatment, and medical research.",
                subjects=["Medicine", "Clinical Hematology", "Oncology"])
            cs_id = self._create_venue(db, title="Journal of Computational Methods",
                scope="Computational methods for numerical simulation and data analysis.",
                subjects=["Computer Science", "Scientific Computing", "Mathematics"])

            retrieved_candidates = []
            for vid in [med_id, cs_id]:
                venue = db.query(Venue).filter(Venue.id == vid).first()
                doc, meta = academic_index_service.build_venue_document(venue)
                retrieved_candidates.append(self._indexed_candidate(
                    record_id=f"venue:{vid}", collection="venue_profiles",
                    document=doc, metadata=meta, score=0.85,
                ))

            request = journal_match_service.create_match_request(
                db, current_user=self.user,
                payload=MatchRequestCreate(
                    session_id=self.session.id,
                    text="Python library for large-scale numerical computing with efficient array operations.",
                    desired_venue_type="journal", include_cfps=False, top_k=5,
                ),
            )
            with patch("app.services.journal_match.service.manuscript_retriever.retrieve", return_value=retrieved_candidates):
                journal_match_service.run_request(db, current_user=self.user, request_id=request.id)

            result = journal_match_service.get_result(db, current_user=self.user, request_id=request.id)
            rows, _summary = build_legacy_journal_payload(result)
            journal_titles = [row["journal"] for row in rows]

        # The CS venue should appear, the medical one should not
        self.assertTrue(
            any("Computational" in t or "Methods" in t for t in journal_titles),
            msg=f"Expected computing venue, got {journal_titles}",
        )


if __name__ == "__main__":
    unittest.main()
