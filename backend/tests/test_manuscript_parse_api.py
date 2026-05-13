from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.v1.endpoints.manuscripts import parse_manuscript
from app.schemas.academic import ManuscriptParseRequest
try:
    from .support import SAMPLE_MANUSCRIPT, TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import SAMPLE_MANUSCRIPT, TestEnvironment


class ManuscriptParseApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()

    def tearDown(self) -> None:
        self.env.close()

    def test_parse_manuscript_text_payload(self) -> None:
        with self.env.session() as db:
            response = parse_manuscript(
                payload=ManuscriptParseRequest(text=SAMPLE_MANUSCRIPT, title="Adaptive Retrieval for Scientific Knowledge Graphs"),
                db=db,
                current_user=self.user,
            )
            self.assertEqual(response.manuscript.title, "Adaptive Retrieval for Scientific Knowledge Graphs")
            self.assertGreaterEqual(response.assessment.keyword_count, 3)
            self.assertTrue(response.assessment.abstract_present)

    def test_parse_manuscript_accepts_legacy_text_field(self) -> None:
        with self.env.session() as db:
            response = parse_manuscript(
                payload=ManuscriptParseRequest.model_validate({"manuscript_text": SAMPLE_MANUSCRIPT}),
                db=db,
                current_user=self.user,
            )
            self.assertIn("Adaptive Retrieval", response.manuscript.title or "")


if __name__ == "__main__":
    unittest.main()
