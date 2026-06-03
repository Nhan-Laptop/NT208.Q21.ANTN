from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.tools.citation_checker import CitationCheckResult, CitationChecker, ReferenceMetadata


OPENALEX_WORK = {
    "id": "https://openalex.org/W1234567890",
    "doi": "https://doi.org/10.5555/transformer",
    "display_name": "Transformer Paper",
    "publication_year": 2024,
    "primary_location": {
        "landing_page_url": "https://example.org/paper",
        "source": {"display_name": "Journal of Exact Identifiers"},
    },
    "authorships": [
        {"author": {"display_name": "Alice Nguyen"}},
        {"author": {"display_name": "Bao Tran"}},
    ],
    "biblio": {"volume": "12", "issue": "3", "first_page": "11", "last_page": "19"},
    "ids": {
        "openalex": "https://openalex.org/W1234567890",
        "pmid": "https://pubmed.ncbi.nlm.nih.gov/12345678",
        "pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567",
    },
}


class _StubClient:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    def get(self, _url: str) -> httpx.Response:
        return self._response


class CitationIdentifierExactTest(unittest.TestCase):
    def test_extract_exact_identifiers_detects_supported_formats(self) -> None:
        checker = CitationChecker()

        text = (
            "PMID: 12345678\n"
            "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/\n"
            "openalex:W1234567890"
        )
        identifiers = checker.extract_exact_identifiers(text)

        self.assertEqual(
            [(item["identifier_type"], item["identifier"]) for item in identifiers],
            [("pmid", "12345678"), ("pmcid", "PMC1234567"), ("openalex", "W1234567890")],
        )

    def test_pmid_exact_identifier_verifies_via_openalex(self) -> None:
        checker = CitationChecker()
        response = httpx.Response(
            200,
            json=OPENALEX_WORK,
            request=httpx.Request("GET", "https://api.openalex.org/works/pmid:12345678"),
        )

        with patch.object(checker, "_get_client", return_value=_StubClient(response)):
            results = checker.verify("PMID: 12345678")

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.status, "IDENTIFIER_VERIFIED")
        self.assertEqual(result.verification_mode, "identifier_exact")
        self.assertEqual(result.input_identifier, "12345678")
        self.assertEqual(result.input_identifier_type, "pmid")
        self.assertEqual(result.matched_identifier, "12345678")
        self.assertEqual(result.matched_identifier_type, "pmid")
        self.assertEqual(result.matched_doi, "10.5555/transformer")
        self.assertEqual(result.matched_title, "Transformer Paper")
        self.assertEqual(result.completed_metadata["external_id"], "https://openalex.org/W1234567890")
        self.assertEqual(result.completed_metadata["external_id_type"], "openalex")
        self.assertIn("https://doi.org/10.5555/transformer", result.formatted_apa or "")
        self.assertEqual(result.metadata_consistency, "not_provided")
        self.assertEqual(result.source_diagnostics["openalex"]["state"], "matched")
        self.assertTrue(result.search_attempted)
        self.assertEqual(result.search_strategy, "exact_lookup")

    def test_identifier_not_found_does_not_fall_back_to_metadata_match(self) -> None:
        checker = CitationChecker()
        response = httpx.Response(
            404,
            json={"error": "not found"},
            request=httpx.Request("GET", "https://api.openalex.org/works/pmcid:PMC1234567"),
        )

        with (
            patch.object(checker, "_get_client", return_value=_StubClient(response)),
            patch(
                "app.services.tools.citation_checker.search_crossref_candidates",
                side_effect=AssertionError("metadata match must not run for exact identifier"),
            ),
            patch(
                "app.services.tools.citation_checker.search_openalex_candidates",
                side_effect=AssertionError("metadata match must not run for exact identifier"),
            ),
        ):
            results = checker.verify("PMCID: PMC1234567")

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.status, "IDENTIFIER_NOT_FOUND")
        self.assertEqual(result.input_identifier, "PMC1234567")
        self.assertEqual(result.input_identifier_type, "pmcid")
        self.assertEqual(result.source, "identifier_exact_lookup")
        self.assertEqual(result.source_diagnostics["openalex"]["state"], "no_match")
        self.assertEqual(result.metadata_consistency, "not_provided")

    def test_identifier_exact_compare_reports_metadata_mismatch(self) -> None:
        checker = CitationChecker()
        response = httpx.Response(
            200,
            json=OPENALEX_WORK,
            request=httpx.Request("GET", "https://api.openalex.org/works/pmid:12345678"),
        )
        mismatched_ref = ReferenceMetadata(
            raw="Wrong Identifier Title",
            title="Wrong Identifier Title",
            authors=[],
            year=None,
            confidence=0.85,
        )

        with (
            patch.object(checker, "_get_client", return_value=_StubClient(response)),
            patch.object(checker, "_reference_from_exact_context", return_value=mismatched_ref),
        ):
            result = checker.verify_identifier_exact(
                "12345678",
                "pmid",
                citation_context={"raw": "Wrong Identifier Title PMID: 12345678"},
            )

        self.assertEqual(result.status, "IDENTIFIER_VERIFIED")
        self.assertEqual(result.metadata_consistency, "mismatch")
        self.assertEqual(result.field_evidence["title"]["verdict"], "mismatch")
        self.assertIn("conflicts with the resolved record", result.reason or "")
        self.assertIn("supplied metadata differs", result.warning or "")

    def test_doi_verified_wins_over_duplicate_pmid_for_same_work(self) -> None:
        checker = CitationChecker()
        doi_verified = CitationCheckResult(
            citation="10.5555/transformer",
            status="DOI_VERIFIED",
            doi="10.5555/transformer",
            title="Transformer Paper",
            authors=["Alice Nguyen", "Bao Tran"],
            year=2024,
            source="crossref",
            confidence=1.0,
        )
        response = httpx.Response(
            200,
            json=OPENALEX_WORK,
            request=httpx.Request("GET", "https://api.openalex.org/works/pmid:12345678"),
        )

        with (
            patch.object(checker, "_verify_doi_crossref", return_value=doi_verified),
            patch.object(checker, "_get_client", return_value=_StubClient(response)),
        ):
            results = checker.verify("DOI: 10.5555/transformer PMID: 12345678")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "DOI_VERIFIED")
        self.assertEqual(results[0].matched_doi, "10.5555/transformer")


if __name__ == "__main__":
    unittest.main()
