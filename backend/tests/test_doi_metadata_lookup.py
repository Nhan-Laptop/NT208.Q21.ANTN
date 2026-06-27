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
        self.assertEqual(metadata["author_details"][0]["name"], "C. R. Harris")

    def test_run_doi_metadata_lookup_prioritizes_authors_when_query_requests_authors(self) -> None:
        metadata = {
            "doi": "10.1038/s41586-020-2649-2",
            "title": "Array programming with NumPy",
            "authors": ["Charles R. Harris", "K. Jarrod Millman", "Stéfan J. van der Walt"],
            "author_details": [
                {"name": "Charles R. Harris"},
                {"name": "K. Jarrod Millman"},
                {"name": "Stéfan J. van der Walt"},
            ],
            "journal": "Nature",
            "publisher": "Springer Nature",
            "publication_year": 2020,
            "verification_status": "Valid DOI",
            "confidence": 1.0,
            "source": "Crossref",
            "missing_fields": [],
            "notes": [],
        }

        with (
            self.env.session() as db,
            patch.object(chat_service, "_resolve_doi_metadata", return_value=(metadata, "verified")),
        ):
            message_type, text, payload = chat_service._run_doi_metadata_lookup(
                db,
                "10.1038/s41586-020-2649-2",
                user_message="các tác giả của 10.1038/s41586-020-2649-2",
            )

        self.assertEqual(message_type, "text")
        self.assertEqual(payload["requested_field"], "authors")
        self.assertEqual(payload["data"]["authors"][0], "Charles R. Harris")
        self.assertIn('Các tác giả của bài "Array programming with NumPy" là:', text)
        self.assertIn("1. Charles R. Harris", text)
        self.assertIn("3. Stéfan J. van der Walt", text)

    def test_run_doi_metadata_lookup_detects_compact_doi_prefix_and_journal_field(self) -> None:
        metadata = {
            "doi": "10.1038/s41586-020-2649-2",
            "title": "Array programming with NumPy",
            "authors": ["Charles R. Harris"],
            "journal": "Nature",
            "publisher": "Springer Nature",
            "publication_year": 2020,
            "verification_status": "Valid DOI",
            "confidence": 1.0,
            "source": "Crossref",
            "missing_fields": [],
            "notes": [],
        }
        query = "journal của DOI10.1038/s41586-020-2649-2 là gì?"

        with (
            self.env.session() as db,
            patch.object(chat_service, "_resolve_doi_metadata", return_value=(metadata, "verified")),
        ):
            extracted_doi = chat_service._extract_first_doi(query)
            message_type, text, payload = chat_service._run_doi_metadata_lookup(
                db,
                extracted_doi or "",
                user_message=query,
            )

        self.assertEqual(extracted_doi, "10.1038/s41586-020-2649-2")
        self.assertTrue(chat_service._is_doi_metadata_request(query))
        self.assertEqual(chat_service._detect_doi_requested_field(query), "journal")
        self.assertEqual(message_type, "text")
        self.assertEqual(payload["requested_field"], "journal")
        self.assertIn("Nature", text)
        self.assertIn("Nguồn metadata: Crossref", text)

    def test_run_doi_metadata_lookup_keeps_generic_summary_when_no_specific_field_requested(self) -> None:
        metadata = {
            "doi": "10.1038/s41586-020-2649-2",
            "title": "Array programming with NumPy",
            "authors": ["Charles R. Harris"],
            "journal": "Nature",
            "publisher": "Springer Nature",
            "publication_year": 2020,
            "verification_status": "Valid DOI",
            "confidence": 1.0,
            "source": "Crossref",
            "missing_fields": [],
            "notes": [],
        }

        with (
            self.env.session() as db,
            patch.object(chat_service, "_resolve_doi_metadata", return_value=(metadata, "verified")),
        ):
            message_type, text, payload = chat_service._run_doi_metadata_lookup(
                db,
                "10.1038/s41586-020-2649-2",
                user_message="phân tích DOI 10.1038/s41586-020-2649-2",
            )

        self.assertEqual(message_type, "text")
        self.assertIsNone(payload["requested_field"])
        self.assertIn("trích xuất metadata chi tiết", text)


if __name__ == "__main__":
    unittest.main()
