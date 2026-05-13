from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.v1.endpoints.journal_match import create_match_request, get_match_results, run_match_request
from app.models.academic_common import VenueType
from app.models.entity_fingerprint import EntityFingerprint
from app.models.venue import Venue
from app.models.venue_metric import VenueMetric
from app.models.venue_subject import VenueSubject
from app.schemas.academic import MatchRequestCreate
from app.services.ingestion.index_service import academic_index_service
from crawler.scheduler import crawl_scheduler
try:
    from .support import SAMPLE_MANUSCRIPT, TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import SAMPLE_MANUSCRIPT, TestEnvironment


class JournalMatchEndToEndApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()
        self.session = self.env.create_chat_session(user=self.user)
        with self.env.session() as db:
            crawl_scheduler.run_crawl_job(db, current_user=self.user, include_live_sources=False)
            venue = Venue(
                title="Journal of Scholarly Retrieval Systems",
                canonical_title="Journal of Scholarly Retrieval Systems",
                venue_type=VenueType.JOURNAL,
                publisher="Trusted Retrieval Society",
                homepage_url="https://trusted.example.org/jsrs",
                aims_scope="Scientific retrieval, biomedical NLP, graph learning, ranking systems, and reproducible academic recommendation research.",
                indexed_scopus=True,
                indexed_wos=True,
                is_open_access=False,
                is_hybrid=True,
            )
            db.add(venue)
            db.flush()
            db.add(VenueSubject(venue_id=venue.id, label="Information Retrieval", source="trusted-index", scheme="keyword"))
            db.add(VenueSubject(venue_id=venue.id, label="Scientific Knowledge Graphs", source="trusted-index", scheme="keyword"))
            db.add(VenueMetric(venue_id=venue.id, metric_year=2026, sjr_quartile="Q1", citescore=7.5))
            db.add(
                EntityFingerprint(
                    entity_type="venue",
                    entity_id=venue.id,
                    source_name="trusted-index",
                    raw_identifier=venue.canonical_title,
                    business_key="trusted-retrieval-society|journal-of-scholarly-retrieval-systems",
                )
            )
            db.commit()
            academic_index_service.upsert_venue(db, venue.id)

    def tearDown(self) -> None:
        self.env.close()

    def test_create_run_and_fetch_results(self) -> None:
        with self.env.session() as db:
            request = create_match_request(
                payload=MatchRequestCreate(
                    session_id=self.session.id,
                    text=SAMPLE_MANUSCRIPT,
                    desired_venue_type="journal",
                    min_quartile="Q2",
                    top_k=5,
                ),
                db=db,
                current_user=self.user,
            )
            result = run_match_request(request_id=request.id, db=db, current_user=self.user)
            self.assertEqual(result.request.status, "succeeded")
            self.assertGreater(len(result.candidates), 0)
            self.assertGreater(result.request.retrieval_diagnostics["candidate_count"], 0)

            fetched = get_match_results(request_id=request.id, db=db, current_user=self.user)
            self.assertEqual(fetched.request.id, request.id)

            rerun = run_match_request(request_id=request.id, db=db, current_user=self.user)
            self.assertEqual(rerun.request.status, "succeeded")
            self.assertEqual(len(rerun.candidates), len(result.candidates))
            self.assertEqual(
                rerun.request.retrieval_diagnostics["replaced_candidate_count"],
                len(result.candidates),
            )


if __name__ == "__main__":
    unittest.main()
