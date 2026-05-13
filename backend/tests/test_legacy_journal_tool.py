from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.tools.journal_finder import journal_finder
from app.models.academic_common import VenueType
from app.models.entity_fingerprint import EntityFingerprint
from app.models.venue import Venue
from app.models.venue_metric import VenueMetric
from app.models.venue_subject import VenueSubject
from app.services.ingestion.index_service import academic_index_service
try:
    from .test_support import BackendTestCase
except ImportError:  # pragma: no cover - unittest discover fallback
    from test_support import BackendTestCase


class LegacyJournalToolAdapterTest(BackendTestCase):
    def test_legacy_journal_finder_returns_rows_from_new_index(self) -> None:
        user = self.create_user()
        self.seed_bootstrap(user)
        db = self.db()
        try:
            venue = Venue(
                title="Journal of Scholarly Retrieval Systems",
                canonical_title="Journal of Scholarly Retrieval Systems",
                venue_type=VenueType.JOURNAL,
                publisher="Trusted Retrieval Society",
                homepage_url="https://trusted.example.org/jsrs",
                aims_scope="Scholarly retrieval, journal recommendation, metadata ranking, and scientific embeddings.",
                indexed_scopus=True,
                indexed_wos=True,
                is_open_access=False,
                is_hybrid=True,
            )
            db.add(venue)
            db.flush()
            db.add(VenueSubject(venue_id=venue.id, label="Information Retrieval", source="trusted-index", scheme="keyword"))
            db.add(VenueMetric(venue_id=venue.id, source_id="trusted-index", metric_name="Trusted index"))
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
        finally:
            db.close()
        rows = journal_finder.recommend(
            abstract="We study scholarly retrieval, journal recommendation, and metadata ranking.",
            top_k=3,
        )
        self.assertGreaterEqual(len(rows), 1)
        self.assertIn("journal", rows[0])
        self.assertIn("score", rows[0])


if __name__ == "__main__":
    unittest.main()
