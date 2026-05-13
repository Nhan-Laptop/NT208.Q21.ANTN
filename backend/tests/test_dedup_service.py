from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.entity_fingerprint import EntityFingerprint
from app.services.ingestion.dedup_service import dedup_service
try:
    from .support import TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import TestEnvironment


class DedupServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()

    def tearDown(self) -> None:
        self.env.close()

    def test_url_and_business_key_normalization(self) -> None:
        normalized = dedup_service.normalize_url("HTTPS://Example.org/path/?q=1#frag")
        self.assertEqual(normalized, "https://example.org/path/?q=1")
        self.assertEqual(dedup_service.business_key_for_article("Title", "Venue", 2026, "10.1000/ABC"), "10.1000/abc")

    def test_url_normalization_preserves_identity_query_and_drops_tracking_params(self) -> None:
        first = dedup_service.normalized_url_hash("http://www.wikicfp.com/cfp/servlet/event.showcfp?eventid=195055&utm_source=x")
        second = dedup_service.normalized_url_hash("http://www.wikicfp.com/cfp/servlet/event.showcfp?eventid=195048&utm_source=x")
        self.assertNotEqual(first, second)
        self.assertEqual(
            dedup_service.normalize_url("https://example.org/path?eventid=1&utm_medium=email&fbclid=abc"),
            "https://example.org/path?eventid=1",
        )

    def test_upsert_reuses_existing_fingerprint(self) -> None:
        with self.env.session() as db:
            first = dedup_service.upsert_fingerprint(
                db,
                entity_type="article",
                entity_id="entity-a",
                source_name="seed",
                raw_identifier="row-1",
                normalized_url_hash=dedup_service.normalized_url_hash("https://example.org/a"),
                business_key=dedup_service.business_key_for_article("Title", "Venue", 2026, "10.1000/abc"),
                content_fingerprint=dedup_service.content_fingerprint("Title", "Abstract"),
            )
            db.commit()
            first_id = first.id

            second = dedup_service.upsert_fingerprint(
                db,
                entity_type="article",
                entity_id="entity-b",
                source_name="seed",
                raw_identifier="row-2",
                normalized_url_hash=dedup_service.normalized_url_hash("https://example.org/b"),
                business_key=dedup_service.business_key_for_article("Title", "Venue", 2026, "10.1000/abc"),
                content_fingerprint=dedup_service.content_fingerprint("Title", "Abstract v2"),
            )
            db.commit()

            rows = db.query(EntityFingerprint).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(second.id, first_id)
            self.assertEqual(rows[0].entity_id, "entity-b")

    def test_cross_source_match_preserves_source_fingerprints(self) -> None:
        business_key = dedup_service.business_key_for_article("Title", "Venue", 2026, "10.1000/abc")
        with self.env.session() as db:
            first = dedup_service.upsert_fingerprint(
                db,
                entity_type="article",
                entity_id="entity-a",
                source_name="source-a",
                raw_identifier="row-a",
                normalized_url_hash=dedup_service.normalized_url_hash("https://example.org/a"),
                business_key=business_key,
                content_fingerprint=dedup_service.content_fingerprint("Title", "Abstract"),
            )
            db.commit()

            existing = dedup_service.find_existing(
                db,
                entity_type="article",
                source_name="source-b",
                raw_identifier="row-b",
                normalized_url_hash=dedup_service.normalized_url_hash("https://example.org/b"),
                business_key=business_key,
                content_fingerprint=dedup_service.content_fingerprint("Title", "Abstract"),
            )
            self.assertEqual(existing.id, first.id)

            second = dedup_service.upsert_fingerprint(
                db,
                entity_type="article",
                entity_id=existing.entity_id,
                source_name="source-b",
                raw_identifier="row-b",
                normalized_url_hash=dedup_service.normalized_url_hash("https://example.org/b"),
                business_key=business_key,
                content_fingerprint=dedup_service.content_fingerprint("Title", "Abstract"),
            )
            db.commit()

            rows = db.query(EntityFingerprint).order_by(EntityFingerprint.source_name).all()
            self.assertEqual(len(rows), 2)
            self.assertNotEqual(first.id, second.id)
            self.assertEqual([row.source_name for row in rows], ["source-a", "source-b"])
            self.assertEqual({row.entity_id for row in rows}, {"entity-a"})


if __name__ == "__main__":
    unittest.main()
