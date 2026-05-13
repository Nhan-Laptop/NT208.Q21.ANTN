from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.v1.endpoints.chat import create_completion
from app.api.v1.endpoints.tools import journal_match
from app.models.academic_common import VenueType
from app.models.chat_session import SessionMode
from app.models.entity_fingerprint import EntityFingerprint
from app.models.venue import Venue
from app.models.venue_subject import VenueSubject
from app.schemas.chat import ChatCompletionRequest
from app.schemas.tools import JournalMatchRequest
from app.services.ingestion.index_service import academic_index_service
from crawler.scheduler import crawl_scheduler
try:
    from .support import SAMPLE_MANUSCRIPT, TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import SAMPLE_MANUSCRIPT, TestEnvironment


class ChatJournalModeRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()
        self.session = self.env.create_chat_session(user=self.user, mode=SessionMode.JOURNAL_MATCH)
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

    def test_legacy_tool_endpoint_accepts_legacy_payload_shape(self) -> None:
        with self.env.session() as db:
            response = journal_match(
                payload=JournalMatchRequest.model_validate(
                    {"session_id": self.session.id, "text": SAMPLE_MANUSCRIPT, "title": "Adaptive Retrieval"}
                ),
                db=db,
                current_user=self.user,
            )
            self.assertEqual(response.type, "journal_list")
            self.assertGreaterEqual(len(response.data), 1)

    def test_chat_journal_mode_returns_structured_tool_payload(self) -> None:
        with self.env.session() as db:
            response = create_completion(
                payload=ChatCompletionRequest(session_id=self.session.id, user_message=SAMPLE_MANUSCRIPT),
                db=db,
                current_user=self.user,
            )
            self.assertEqual(response.assistant_message.message_type, "journal_list")
            tool_results = response.assistant_message.tool_results
            self.assertEqual(tool_results["type"], "journal_list")
            self.assertIn("request_id", tool_results)
            summary = (response.assistant_message.content or "").lower()
            self.assertTrue("gợi ý" in summary or "fallback" in summary)
            if tool_results["data"]:
                self.assertIn("recommendation", tool_results["data"][0]["reason"].lower())

    def test_chat_journal_mode_handles_match_failure_gracefully(self) -> None:
        with patch("app.services.journal_match.service.manuscript_retriever.retrieve", side_effect=RuntimeError("retrieval down")):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(session_id=self.session.id, user_message=SAMPLE_MANUSCRIPT),
                    db=db,
                    current_user=self.user,
                )
        self.assertEqual(response.assistant_message.message_type, "journal_list")
        content = response.assistant_message.content or ""
        self.assertIn("chưa thể hoàn tất journal matching", content.lower())
        self.assertNotIn("retrieval down", content)


if __name__ == "__main__":
    unittest.main()
