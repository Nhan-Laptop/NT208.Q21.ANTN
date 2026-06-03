from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.chat_service import chat_service
from app.services.tools.citation_checker import CitationCheckResult

try:
    from .support import TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import TestEnvironment


class DoiMetadataLookupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()

    def tearDown(self) -> None:
        self.env.close()

    def test_resolve_doi_metadata_returns_structured_fields_and_missing_notes(self) -> None:
        verified = CitationCheckResult(
            citation="10.1038/s41586-020-2649-2",
            status="DOI_VERIFIED",
            doi="10.1038/s41586-020-2649-2",
            title="Array programming with NumPy",
            authors=["C. R. Harris", "K. J. Millman"],
            year=2020,
            source="crossref",
            confidence=1.0,
            metadata={
                "crossref": {
                    "DOI": "10.1038/s41586-020-2649-2",
                    "title": ["Array programming with NumPy"],
                    "container-title": ["Nature"],
                    "publisher": "Springer Science and Business Media LLC",
                    "URL": "https://doi.org/10.1038/s41586-020-2649-2",
                },
            },
        )

        with (
            self.env.session() as db,
            patch("app.services.chat_service.citation_checker.verify_doi_exact", return_value=verified),
            patch("app.services.chat_service.citation_checker._verify_doi_openalex_exact", return_value=None),
        ):
            metadata, status = chat_service._resolve_doi_metadata(db, "10.1038/s41586-020-2649-2")

        self.assertEqual(status, "verified")
        self.assertEqual(metadata["verification_status"], "Valid DOI")
        self.assertEqual(metadata["title"], "Array programming with NumPy")
        self.assertEqual(metadata["journal"], "Nature")
        self.assertEqual(metadata["publisher"], "Springer Science and Business Media LLC")
        self.assertEqual(metadata["publication_year"], 2020)
        self.assertEqual(metadata["source"], "Crossref")
        self.assertAlmostEqual(metadata["confidence"], 1.0)
        self.assertIsNone(metadata["research_field"])
        self.assertEqual(
            metadata["research_field_note"],
            "Not directly available from Crossref/OpenAlex metadata.",
        )
        self.assertEqual(metadata["main_topic"], "Array programming with NumPy")
        self.assertEqual(metadata["main_topic_basis"], "inferred")
        self.assertIn("research_field", metadata["missing_fields"])
        self.assertIn(
            "Not directly available from Crossref/OpenAlex metadata.",
            metadata["notes"],
        )


if __name__ == "__main__":
    unittest.main()
