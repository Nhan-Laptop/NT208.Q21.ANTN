from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.article import Article
from app.models.cfp_event import CFPEvent
from app.models.crawl_state import CrawlState
from app.models.entity_fingerprint import EntityFingerprint
from app.models.raw_source_snapshot import RawSourceSnapshot
from app.models.venue import Venue
from app.services.ingestion.index_service import academic_index_service
from crawler.scheduler import crawl_scheduler

try:
    from .support import TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import TestEnvironment


class CrawlPipelineIdempotencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()

    def tearDown(self) -> None:
        self.env.close()

    def _counts(self, db):
        return {
            "venues": db.query(Venue).count(),
            "articles": db.query(Article).count(),
            "cfps": db.query(CFPEvent).count(),
            "snapshots": db.query(RawSourceSnapshot).count(),
            "fingerprints": db.query(EntityFingerprint).count(),
            "states": db.query(CrawlState).count(),
        }

    def test_repeated_bootstrap_crawl_updates_without_duplicate_rows_or_vectors(self) -> None:
        with self.env.session() as db:
            first_job = crawl_scheduler.run_crawl_job(db, current_user=self.user, include_live_sources=False)
            first_counts = self._counts(db)
            first_index_counts = academic_index_service.collection_counts()

            second_job = crawl_scheduler.run_crawl_job(db, current_user=self.user, include_live_sources=False)
            second_counts = self._counts(db)
            second_index_counts = academic_index_service.collection_counts()

            self.assertEqual(first_job.status.value, "succeeded")
            self.assertEqual(second_job.status.value, "succeeded")
            self.assertGreater(first_job.records_created, 0)
            self.assertEqual(second_job.records_created, 0)
            self.assertEqual(second_job.records_seen, second_job.records_updated)
            self.assertEqual(second_job.records_seen, second_job.records_deduped)
            self.assertEqual(first_counts, second_counts)
            self.assertEqual(first_index_counts, second_index_counts)
            self.assertEqual(second_counts["states"], 1)
            self.assertEqual(second_job.records_indexed, second_job.records_seen)


if __name__ == "__main__":
    unittest.main()
