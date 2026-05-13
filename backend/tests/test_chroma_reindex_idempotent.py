from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.article import Article
from app.services.embeddings.specter2_service import specter2_service
from app.services.ingestion.index_service import academic_index_service
from crawler.scheduler import crawl_scheduler
try:
    from .support import TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import TestEnvironment


class ChromaReindexIdempotentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()
        with self.env.session() as db:
            crawl_scheduler.run_crawl_job(db, current_user=self.user, include_live_sources=False)

    def tearDown(self) -> None:
        self.env.close()

    def test_reindex_is_idempotent_and_prunes_stale_documents(self) -> None:
        with self.env.session() as db:
            first = academic_index_service.reindex_all(db)
            counts_after_first = academic_index_service.collection_counts()
            second = academic_index_service.reindex_all(db)
            counts_after_second = academic_index_service.collection_counts()
            self.assertEqual(first, second)
            self.assertEqual(counts_after_first, counts_after_second)

            article = db.query(Article).first()
            self.assertIsNotNone(article)
            db.delete(article)
            db.commit()

            academic_index_service.reindex_all(db)
            counts_after_delete = academic_index_service.collection_counts()
            self.assertEqual(counts_after_delete["article_exemplars"], counts_after_second["article_exemplars"] - 1)

    def test_article_and_cfp_index_metadata_carries_venue_policy_fields(self) -> None:
        with self.env.session() as db:
            academic_index_service.reindex_all(db)

        article_rows = academic_index_service._collection("article_exemplars").get(include=["metadatas"])
        cfp_rows = academic_index_service._collection("cfp_notices").get(include=["metadatas"])
        article_metadata = article_rows["metadatas"][0]
        cfp_metadata = cfp_rows["metadatas"][0]

        for metadata in (article_metadata, cfp_metadata):
            self.assertIn("sjr_quartile", metadata)
            self.assertIn("indexed_scopus", metadata)
            self.assertIn("avg_review_weeks", metadata)
            self.assertIn("apc_usd", metadata)

    def test_full_reindex_resets_collections_from_previous_embedding_model(self) -> None:
        specter2_service._backend = "hash-fallback"
        specter2_service._loaded_model_name = "current-model"
        specter2_service._model = "hash-fallback"
        academic_index_service._reset_collection("venue_profiles")
        collection = academic_index_service._collection("venue_profiles")
        collection.upsert(
            ids=["venue:old"],
            documents=["old document"],
            metadatas=[{"embedding_model": "old-model"}],
            embeddings=[[1.0, 0.0, 0.0]],
        )

        academic_index_service._reset_collections_for_current_embedding()

        self.assertEqual(academic_index_service._collection("venue_profiles").count(), 0)


if __name__ == "__main__":
    unittest.main()
