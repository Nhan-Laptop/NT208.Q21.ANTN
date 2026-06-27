from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.v1.endpoints.tools import router
from app.models.chat_message import ChatMessage, MessageType
from app.models.chat_session import SessionMode
from app.services.tools.citation.models import CandidateWork
from app.services.tools.citation_batch_service import CitationBatchService, is_verified_citation_status
from app.services.tools.citation_checker import CitationCheckResult, citation_checker

try:
    from .test_support import BackendTestCase
except ImportError:  # pragma: no cover - unittest discover fallback
    from test_support import BackendTestCase


class CitationBatchServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = CitationBatchService()

    def test_generic_request_without_reference_items_returns_no_occurrences(self) -> None:
        self.assertEqual(self.service._extract_occurrences("Please verify this reference for me"), [])

    def test_extract_occurrences_skips_common_preamble_blocks(self) -> None:
        cases = (
            (
                "Kiểm tra các bài sau:\n"
                "1. 10.1038/s41586-020-2649-2\n"
                "2. 10.1016/S0140-6736(97)11096-0\n",
                ["10.1038/s41586-020-2649-2", "10.1016/S0140-6736(97)11096-0"],
            ),
            (
                "References:\n"
                "1. 10.1038/s41586-020-2649-2\n"
                "2. 10.1016/S0140-6736(97)11096-0\n",
                ["10.1038/s41586-020-2649-2", "10.1016/S0140-6736(97)11096-0"],
            ),
            (
                "Please check these citations:\n"
                "- 10.1038/s41586-020-2649-2\n"
                "- 10.1016/S0140-6736(97)11096-0\n",
                ["10.1038/s41586-020-2649-2", "10.1016/S0140-6736(97)11096-0"],
            ),
        )

        for text, expected_dois in cases:
            with self.subTest(text=text.splitlines()[0]):
                occurrences = self.service._extract_occurrences(text)
                normalized_expected = [citation_checker.normalize_doi(doi) for doi in expected_dois]

                self.assertEqual(len(occurrences), 2)
                self.assertEqual([item["type"] for item in occurrences], ["doi", "doi"])
                self.assertEqual([item["doi"] for item in occurrences], normalized_expected)
                self.assertFalse(any("Kiểm tra các bài sau" in item["raw"] for item in occurrences))
                self.assertFalse(any(item["type"] == "raw_reference" for item in occurrences))

    def test_extract_occurrences_preserves_full_numbered_reference_rows(self) -> None:
        text = (
            "References:\n"
            "1. WHO (2012). Dengue and dengue haemorrhagic fever. World Health Organization.\n"
            "2. Gubler DJ. Dengue and dengue hemorrhagic fever. Clin Microbiol Rev 1998; 11: 480 96.\n"
        )

        occurrences = self.service._extract_occurrences(text)

        self.assertEqual(len(occurrences), 2)
        self.assertEqual([item["source_number"] for item in occurrences], [1, 2])
        self.assertEqual(
            occurrences[0]["raw"],
            "WHO (2012). Dengue and dengue haemorrhagic fever. World Health Organization.",
        )
        self.assertEqual(
            occurrences[1]["raw"],
            "Gubler DJ. Dengue and dengue hemorrhagic fever. Clin Microbiol Rev 1998; 11: 480 96.",
        )
        self.assertFalse(any(item["raw"] == "References:" for item in occurrences))

    def test_extract_occurrences_preserves_source_numbers_for_offset_lists(self) -> None:
        text = (
            "5. WHO (2012). Dengue and dengue haemorrhagic fever. World Health Organization.\n"
            "6. WHO/TDR(2009). Dengue: guidelines for diagnosis, treatment, prevention and control. Geneva: World Health Organization.\n"
            "7. Chowell G, Sanchez F. Climate-based descriptive models of dengue fever: the 2002 epidemic in Colima, Mexico. J Environ Health 2006; 68: 40 4, 55.\n"
        )

        occurrences = self.service._extract_occurrences(text)

        self.assertEqual(len(occurrences), 3)
        self.assertEqual([item["source_number"] for item in occurrences], [5, 6, 7])
        self.assertEqual([item["raw"].split(". ", 1)[0] for item in occurrences], [
            "WHO (2012)",
            "WHO/TDR(2009)",
            "Chowell G, Sanchez F",
        ])

    def test_extract_occurrences_keeps_multiline_reference_together(self) -> None:
        text = (
            "10. Hii YL, Rocklov J, Ng N, Tang CS, Pang FY, Sauerborn R.\n"
            "Climate variability and increase in intensity and magnitude of dengue incidence in Singapore.\n"
            "Glob Health Action 2009; 2: 2036, doi: http://dx.doi.org/10.3402/gha.v2i0.2036\n"
        )

        occurrences = self.service._extract_occurrences(text)

        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0]["type"], "doi")
        self.assertEqual(occurrences[0]["doi"], "10.3402/gha.v2i0.2036")
        self.assertIn("Climate variability and increase in intensity", occurrences[0]["raw"])
        self.assertIn("Glob Health Action 2009", occurrences[0]["raw"])
        self.assertIn("\n", occurrences[0]["raw"])

    def test_extract_occurrences_splits_bullet_list(self) -> None:
        text = (
            "- WHO (2012). Dengue and dengue haemorrhagic fever. World Health Organization.\n"
            "- Gubler DJ. Dengue and dengue hemorrhagic fever. Clin Microbiol Rev 1998; 11: 480 96.\n"
        )

        occurrences = self.service._extract_occurrences(text)

        self.assertEqual(len(occurrences), 2)
        self.assertEqual([item["source_number"] for item in occurrences], [None, None])
        self.assertEqual([item["source_type"] for item in occurrences], [
            "scholarly_reference",
            "scholarly_reference",
        ])

    def test_extract_occurrences_classifies_blog_description_without_url(self) -> None:
        occurrences = self.service._extract_occurrences(
            "Một bài blog cá nhân về dengue prevention in Singapore năm 2013."
        )

        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0]["type"], "blog_or_non_scholarly")
        self.assertEqual(occurrences[0]["source_type"], "blog_or_non_scholarly")

    def test_batch_doi_extraction_does_not_treat_doi_prefix_as_list_number(self) -> None:
        occurrences = self.service._extract_occurrences("10.1038/s41586-020-2649-2")

        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0]["type"], "doi")
        self.assertEqual(occurrences[0]["doi"], "10.1038/s41586-020-2649-2")
        self.assertIsNone(occurrences[0]["source_number"])

    def test_batch_summary_uses_real_occurrence_count_for_clean_doi_lists(self) -> None:
        text = (
            "Kiểm tra các bài sau:\n"
            "1. 10.1038/s41586-020-2649-2\n"
            "2. 10.1016/S0140-6736(97)11096-0\n"
        )

        def _verify_doi_exact(raw_doi: str, citation_context=None):
            normalized = raw_doi.strip().lower()
            return CitationCheckResult(
                citation=normalized,
                status="DOI_VERIFIED",
                doi=normalized,
                title=f"Title for {normalized}",
                source="crossref",
                confidence=1.0,
            )

        with patch("app.services.tools.citation_batch_service.citation_checker.verify_doi_exact", side_effect=_verify_doi_exact):
            report = self.service.verify_text(text)

        self.assertEqual(len(report["results"]), 2)
        self.assertEqual([item["index"] for item in report["results"]], [1, 2])
        self.assertEqual(report["summary"]["total_count"], 2)
        self.assertEqual(report["summary"]["verified_count"], 2)
        self.assertEqual(report["summary"]["problem_count"], 0)
        self.assertEqual(report["summary"]["review_count"], 0)
        self.assertEqual(report["summary"]["temporary_issue_count"], 0)
        self.assertIn("Mình đã kiểm tra 2 mục trích dẫn", report["text"])
        self.assertFalse(any("Kiểm tra các bài sau" in item["raw_citation"] for item in report["results"]))

    def test_web_url_rows_use_review_status_not_academic_verified(self) -> None:
        with patch(
            "app.services.tools.citation_batch_service._PUBLISHER_META_SOURCE.enrich_candidate",
            return_value=CandidateWork(
                source="web_url",
                title="Example blog post",
                year=2024,
                url="https://example.com/my-personal-blog-post",
                resolved_url="https://example.com/my-personal-blog-post",
                source_domain="example.com",
                evidence_urls=["https://example.com/my-personal-blog-post"],
            ),
        ):
            report = self.service.verify_text("https://example.com/my-personal-blog-post")

        self.assertEqual(report["summary"]["total_count"], 1)
        self.assertEqual(report["results"][0]["status"], "UNVERIFIED_NO_DOI")
        self.assertEqual(report["results"][0]["source_type"], "web_url")
        self.assertEqual(report["results"][0]["matched_title"], "Example blog post")
        self.assertIsNone(report["results"][0]["matched_doi"])
        self.assertNotIn(report["results"][0]["status"], {"DOI_VERIFIED", "METADATA_VERIFIED"})

    def test_blog_description_without_url_returns_review_row(self) -> None:
        report = self.service.verify_text("Một bài blog cá nhân về dengue prevention in Singapore năm 2013.")

        self.assertEqual(report["summary"]["total_count"], 1)
        self.assertEqual(report["results"][0]["status"], "UNVERIFIED_NO_DOI")
        self.assertEqual(report["results"][0]["source_type"], "blog_or_non_scholarly")
        self.assertIn("direct URL", report["results"][0]["reason"])
        self.assertIn("title, author/organization, and publication date", report["results"][0]["reason"])

    def test_web_url_rows_do_not_route_into_academic_metadata_matching(self) -> None:
        with (
            patch(
                "app.services.tools.citation_batch_service._PUBLISHER_META_SOURCE.enrich_candidate",
                return_value=CandidateWork(
                    source="web_url",
                    title="Example page",
                    url="https://example.com/post",
                    resolved_url="https://example.com/post",
                    source_domain="example.com",
                ),
            ),
            patch(
                "app.services.tools.citation_batch_service.citation_checker._verify_metadata_match",
                side_effect=AssertionError("web URL should not be promoted into academic metadata verification"),
            ),
        ):
            report = self.service.verify_text("https://example.com/post")

        self.assertEqual(report["results"][0]["source_type"], "web_url")
        self.assertEqual(report["results"][0]["status"], "UNVERIFIED_NO_DOI")

    def test_mixed_batch_with_doi_blog_and_academic_reference_keeps_all_rows(self) -> None:
        text = (
            "Kiểm tra các nguồn sau:\n"
            "1. 10.1038/s41586-020-2649-2\n"
            "2. Một blog cá nhân về dengue prevention in Singapore.\n"
            "3. Gubler DJ. Dengue and dengue hemorrhagic fever. Clin Microbiol Rev 1998; 11: 480 96.\n"
        )

        with (
            patch(
                "app.services.tools.citation_batch_service.citation_checker.verify_doi_exact",
                return_value=CitationCheckResult(
                    citation="10.1038/s41586-020-2649-2",
                    status="DOI_VERIFIED",
                    doi="10.1038/s41586-020-2649-2",
                    title="Array programming with NumPy",
                    source="crossref",
                    confidence=1.0,
                ),
            ),
            patch(
                "app.services.tools.citation_batch_service.citation_checker._verify_metadata_match",
                return_value=CitationCheckResult(
                    citation="Gubler DJ. Dengue and dengue hemorrhagic fever. Clin Microbiol Rev 1998; 11: 480 96.",
                    status="METADATA_VERIFIED",
                    matched_title="Dengue and dengue hemorrhagic fever",
                    matched_year=1998,
                    matched_venue="Clin Microbiol Rev",
                    confidence=0.94,
                ),
            ),
        ):
            report = self.service.verify_text(text)

        self.assertEqual(report["summary"]["total_count"], 3)
        self.assertEqual([item["source_number"] for item in report["results"]], [1, 2, 3])
        self.assertEqual(report["results"][0]["status"], "DOI_VERIFIED")
        self.assertEqual(report["results"][1]["source_type"], "blog_or_non_scholarly")
        self.assertEqual(report["results"][1]["status"], "UNVERIFIED_NO_DOI")
        self.assertEqual(report["results"][2]["status"], "METADATA_VERIFIED")

    def test_unexpected_single_row_failure_does_not_abort_the_batch(self) -> None:
        occurrences = [
            {"raw": "10.1000/one", "type": "doi", "doi": "10.1000/one", "source_type": "scholarly_identifier"},
            {"raw": "Broken item", "type": "raw_reference", "source_type": "scholarly_reference"},
            {"raw": "10.1000/two", "type": "doi", "doi": "10.1000/two", "source_type": "scholarly_identifier"},
        ]

        def _verify_side_effect(occurrence, _cache):
            raw = occurrence["raw"]
            if raw == "Broken item":
                raise RuntimeError("boom")
            return CitationCheckResult(
                citation=raw,
                status="DOI_VERIFIED",
                doi=raw,
                title=f"Title for {raw}",
                source="crossref",
                confidence=1.0,
            )

        with (
            patch.object(self.service, "_extract_occurrences", return_value=occurrences),
            patch.object(self.service, "_verify_occurrence", side_effect=_verify_side_effect),
        ):
            report = self.service.verify_text("ignored")

        self.assertEqual(report["summary"]["total_count"], 3)
        self.assertEqual([item["status"] for item in report["results"]], [
            "DOI_VERIFIED",
            "UNVERIFIED",
            "DOI_VERIFIED",
        ])
        self.assertIn("temporary processing issue", report["results"][1]["short_issue"].lower())

    def test_batch_preserves_order_and_keeps_duplicate_occurrences(self) -> None:
        text = (
            "References\n"
            "[1] First paper. doi:10.1000/first\n"
            "[2] Second paper. doi:10.1000/second\n"
            "[3] First paper repeated. doi:10.1000/first\n"
        )

        def _verify_doi_exact(raw_doi: str, citation_context=None):
            normalized = raw_doi.strip().lower()
            return CitationCheckResult(
                citation=normalized,
                status="DOI_VERIFIED",
                doi=normalized,
                title=f"Title for {normalized}",
                source="crossref",
                confidence=1.0,
            )

        with patch("app.services.tools.citation_batch_service.citation_checker.verify_doi_exact", side_effect=_verify_doi_exact) as verify_doi_exact:
            report = self.service.verify_text(text)

        self.assertEqual([item["index"] for item in report["results"]], [1, 2, 3])
        self.assertEqual(
            [item["matched_doi"] for item in report["results"]],
            ["10.1000/first", "10.1000/second", "10.1000/first"],
        )
        self.assertEqual(verify_doi_exact.call_count, 2)

    def test_batch_metadata_cache_does_not_remove_duplicate_rows(self) -> None:
        occurrences = [
            {"raw": "Duplicate metadata citation", "type": "raw_reference"},
            {"raw": "Duplicate metadata citation", "type": "raw_reference"},
        ]

        with (
            patch.object(self.service, "_extract_occurrences", return_value=occurrences),
            patch(
                "app.services.tools.citation_batch_service.citation_checker._verify_metadata_match",
                return_value=CitationCheckResult(
                    citation="Duplicate metadata citation",
                    status="METADATA_VERIFIED",
                    matched_title="Duplicate metadata citation",
                    confidence=0.97,
                ),
            ) as verify_metadata_match,
        ):
            report = self.service.verify_text("ignored")

        self.assertEqual(len(report["results"]), 2)
        self.assertEqual([item["index"] for item in report["results"]], [1, 2])
        self.assertEqual([item["raw_citation"] for item in report["results"]], [
            "Duplicate metadata citation",
            "Duplicate metadata citation",
        ])
        self.assertEqual(verify_metadata_match.call_count, 1)

    def test_status_mapping_and_summary_counts_follow_batch_rules(self) -> None:
        statuses = [
            "DOI_VERIFIED",
            "IDENTIFIER_VERIFIED",
            "METADATA_VERIFIED",
            "LIKELY_MATCH",
            "POSSIBLE_MATCH",
            "AMBIGUOUS_MATCH",
            "UNVERIFIED_NO_DOI",
            "DOI_NOT_FOUND",
            "IDENTIFIER_NOT_FOUND",
            "NO_MATCH_FOUND",
            "PARSE_FAILED",
            "UNVERIFIED",
        ]
        occurrences = [{"raw": f"citation {index}", "type": "raw_reference"} for index, _ in enumerate(statuses, start=1)]
        raw_results = [CitationCheckResult(citation=item["raw"], status=status, confidence=0.75) for item, status in zip(occurrences, statuses)]

        with (
            patch.object(self.service, "_extract_occurrences", return_value=occurrences),
            patch.object(self.service, "_verify_occurrence", side_effect=raw_results),
        ):
            report = self.service.verify_text("ignored")

        result_by_status = {item["status"]: item for item in report["results"]}
        self.assertEqual(result_by_status["DOI_VERIFIED"]["ux_group"], "verified")
        self.assertEqual(result_by_status["IDENTIFIER_VERIFIED"]["ux_group"], "verified")
        self.assertEqual(result_by_status["METADATA_VERIFIED"]["ux_group"], "verified")
        self.assertEqual(result_by_status["LIKELY_MATCH"]["ux_group"], "review")
        self.assertEqual(result_by_status["POSSIBLE_MATCH"]["ux_group"], "review")
        self.assertEqual(result_by_status["AMBIGUOUS_MATCH"]["ux_group"], "review")
        self.assertEqual(result_by_status["UNVERIFIED_NO_DOI"]["ux_group"], "review")
        self.assertEqual(result_by_status["DOI_NOT_FOUND"]["ux_group"], "problem")
        self.assertEqual(result_by_status["IDENTIFIER_NOT_FOUND"]["ux_group"], "problem")
        self.assertEqual(result_by_status["NO_MATCH_FOUND"]["ux_group"], "problem")
        self.assertEqual(result_by_status["PARSE_FAILED"]["ux_group"], "problem")
        self.assertEqual(result_by_status["UNVERIFIED"]["ux_group"], "temporary_issue")

        summary = report["summary"]
        self.assertEqual(summary["total_count"], 12)
        self.assertEqual(summary["verified_count"], 3)
        self.assertEqual(summary["review_count"], 4)
        self.assertEqual(summary["problem_count"], 4)
        self.assertEqual(summary["temporary_issue_count"], 1)
        self.assertEqual(summary["status_counts"]["DOI_VERIFIED"], 1)
        self.assertEqual(summary["status_counts"]["UNVERIFIED"], 1)

    def test_likely_match_does_not_expose_formatted_exports(self) -> None:
        occurrence = {"raw": "Attention is all you need. 2017.", "type": "raw_reference"}
        weak_result = CitationCheckResult(
            citation=occurrence["raw"],
            status="LIKELY_MATCH",
            confidence=0.88,
            completed_metadata={"title": "Attention is all you need"},
            formatted_apa="APA",
            formatted_bibtex="@article{}",
            csl_json={"title": "Attention is all you need"},
        )

        with (
            patch.object(self.service, "_extract_occurrences", return_value=[occurrence]),
            patch.object(self.service, "_verify_occurrence", return_value=weak_result),
        ):
            report = self.service.verify_text("ignored")

        item = report["results"][0]
        self.assertIsNone(item["completed_metadata"])
        self.assertIsNone(item["formatted_apa"])
        self.assertIsNone(item["formatted_bibtex"])
        self.assertIsNone(item["csl_json"])

    def test_ai_summary_failure_still_returns_results(self) -> None:
        occurrence = {"raw": "10.1000/example", "type": "doi", "doi": "10.1000/example"}
        result = CitationCheckResult(
            citation="10.1000/example",
            status="DOI_VERIFIED",
            doi="10.1000/example",
            title="Example title",
            source="crossref",
            confidence=1.0,
        )

        with (
            patch.object(self.service, "_extract_occurrences", return_value=[occurrence]),
            patch.object(self.service, "_verify_occurrence", return_value=result),
            patch.object(self.service, "_maybe_generate_ai_summary", side_effect=RuntimeError("llm exploded")),
        ):
            report = self.service.verify_text("10.1000/example", include_ai_summary=True)

        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["status"], "DOI_VERIFIED")
        self.assertIsNone(report["summary"]["summary_text"])
        self.assertEqual(report["summary"]["default_summary_text"], report["text"])

    def test_doi_not_found_does_not_fall_back_to_metadata_verified(self) -> None:
        occurrence = {"raw": "doi:10.1234/fake", "type": "doi", "doi": "10.1234/fake"}
        not_found = CitationCheckResult(
            citation="10.1234/fake",
            status="DOI_NOT_FOUND",
            doi="10.1234/fake",
            source="doi_exact_lookup",
            confidence=0.0,
        )

        with (
            patch.object(self.service, "_extract_occurrences", return_value=[occurrence]),
            patch("app.services.tools.citation_batch_service.citation_checker.verify_doi_exact", return_value=not_found),
            patch(
                "app.services.tools.citation_batch_service.citation_checker._verify_metadata_match",
                side_effect=AssertionError("metadata fallback must not run for DOI input"),
            ),
        ):
            report = self.service.verify_text("doi:10.1234/fake")

        self.assertEqual(report["results"][0]["status"], "DOI_NOT_FOUND")

    def test_identifier_not_found_does_not_fall_back_to_metadata_verified(self) -> None:
        occurrence = {"raw": "PMID: 12345678", "type": "pmid", "identifier": "12345678"}
        not_found = CitationCheckResult(
            citation="PMID: 12345678",
            status="IDENTIFIER_NOT_FOUND",
            source="identifier_exact_lookup",
            confidence=0.0,
        )

        with (
            patch.object(self.service, "_extract_occurrences", return_value=[occurrence]),
            patch("app.services.tools.citation_batch_service.citation_checker.verify_identifier_exact", return_value=not_found),
            patch(
                "app.services.tools.citation_batch_service.citation_checker._verify_metadata_match",
                side_effect=AssertionError("metadata fallback must not run for exact identifier input"),
            ),
        ):
            report = self.service.verify_text("PMID: 12345678")

        self.assertEqual(report["results"][0]["status"], "IDENTIFIER_NOT_FOUND")

    def test_verified_export_helper_only_allows_verified_statuses(self) -> None:
        verified_statuses = ["DOI_VERIFIED", "IDENTIFIER_VERIFIED", "METADATA_VERIFIED"]
        rejected_statuses = [
            "LIKELY_MATCH",
            "POSSIBLE_MATCH",
            "AMBIGUOUS_MATCH",
            "UNVERIFIED_NO_DOI",
            "DOI_NOT_FOUND",
            "IDENTIFIER_NOT_FOUND",
            "NO_MATCH_FOUND",
            "PARSE_FAILED",
            "UNVERIFIED",
            None,
            "",
        ]

        for status in verified_statuses:
            self.assertTrue(is_verified_citation_status(status), status)

        for status in rejected_statuses:
            self.assertFalse(is_verified_citation_status(status), status)

    def test_split_reference_blocks_keeps_default_dedupe_behavior(self) -> None:
        text = (
            "[1] First paper. doi:10.1000/first\n"
            "[2] Second paper. doi:10.1000/second\n"
            "[3] First paper. doi:10.1000/first\n"
        )

        deduped = citation_checker._split_reference_blocks(text)
        with_duplicates = citation_checker._split_reference_blocks(text, dedupe=False)

        self.assertEqual(len(deduped), 2)
        self.assertEqual(len(with_duplicates), 3)
        self.assertEqual(with_duplicates[0], with_duplicates[2])


class CitationBatchApiTest(BackendTestCase):
    def test_verify_citations_endpoint_returns_summary_and_results(self) -> None:
        user = self.create_user()
        session = self.create_session(user.id, mode=SessionMode.VERIFICATION)
        client = self.build_client(router, current_user=user)
        self.addCleanup(client.close)

        stub_report = {
            "type": "citation_report",
            "data": [
                {
                    "index": 1,
                    "raw_citation": "First citation",
                    "citation": "10.1000/first",
                    "status": "DOI_VERIFIED",
                    "ux_group": "verified",
                    "confidence": 1.0,
                    "matched_title": "First title",
                    "matched_doi": "10.1000/first",
                    "matched_year": 2024,
                    "matched_venue": "Journal One",
                    "short_issue": None,
                    "suggested_action": "Keep the DOI.",
                }
            ],
            "results": [
                {
                    "index": 1,
                    "raw_citation": "First citation",
                    "citation": "10.1000/first",
                    "status": "DOI_VERIFIED",
                    "ux_group": "verified",
                    "confidence": 1.0,
                    "matched_title": "First title",
                    "matched_doi": "10.1000/first",
                    "matched_year": 2024,
                    "matched_venue": "Journal One",
                    "short_issue": None,
                    "suggested_action": "Keep the DOI.",
                }
            ],
            "summary": {
                "total_count": 1,
                "verified_count": 1,
                "review_count": 0,
                "problem_count": 0,
                "temporary_issue_count": 0,
                "status_counts": {"DOI_VERIFIED": 1},
                "summary_text": None,
                "default_summary_text": "One citation verified.",
            },
            "statistics": {"total": 1, "doi_verified": 1, "no_citation_found": False},
            "no_citation_found": False,
            "text": "One citation verified.",
        }

        with patch("app.api.v1.endpoints.tools.citation_batch_service.verify_text", return_value=stub_report):
            response = client.post(
                "/api/v1/tools/verify-citations",
                json={
                    "session_id": session.id,
                    "text": "First citation",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["type"], "citation_report")
        self.assertEqual(payload["summary"]["total_count"], 1)
        self.assertEqual(payload["results"][0]["ux_group"], "verified")
        self.assertEqual(payload["results"][0]["raw_citation"], "First citation")

        db = self.db()
        try:
            persisted = db.query(ChatMessage).filter(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at).all()
            self.assertEqual(len(persisted), 2)
            self.assertEqual(persisted[-1].message_type, MessageType.CITATION_REPORT)
            self.assertEqual(persisted[-1].tool_results["type"], "citation_report")
            self.assertEqual(persisted[-1].tool_results["summary"]["total_count"], 1)
        finally:
            db.close()

    def test_legacy_verify_citation_endpoint_keeps_old_response_shape(self) -> None:
        user = self.create_user(email="legacy@example.com")
        session = self.create_session(user.id, mode=SessionMode.VERIFICATION)
        client = self.build_client(router, current_user=user)
        self.addCleanup(client.close)

        stub_report = {
            "type": "citation_report",
            "data": [
                {
                    "index": 1,
                    "raw_citation": "Legacy citation",
                    "citation": "10.1000/legacy",
                    "status": "DOI_VERIFIED",
                    "ux_group": "verified",
                    "confidence": 1.0,
                    "matched_title": "Legacy title",
                    "matched_doi": "10.1000/legacy",
                    "short_issue": None,
                    "suggested_action": "Keep the DOI.",
                }
            ],
            "results": [
                {
                    "index": 1,
                    "raw_citation": "Legacy citation",
                    "citation": "10.1000/legacy",
                    "status": "DOI_VERIFIED",
                    "ux_group": "verified",
                    "confidence": 1.0,
                    "matched_title": "Legacy title",
                    "matched_doi": "10.1000/legacy",
                    "short_issue": None,
                    "suggested_action": "Keep the DOI.",
                }
            ],
            "summary": {
                "total_count": 1,
                "verified_count": 1,
                "review_count": 0,
                "problem_count": 0,
                "temporary_issue_count": 0,
                "status_counts": {"DOI_VERIFIED": 1},
                "summary_text": None,
                "default_summary_text": "One citation verified.",
            },
            "statistics": {"total": 1, "doi_verified": 1, "no_citation_found": False},
            "no_citation_found": False,
            "text": "One citation verified.",
        }

        with patch("app.api.v1.endpoints.tools.citation_batch_service.verify_text", return_value=stub_report):
            response = client.post(
                "/api/v1/tools/verify-citation",
                json={
                    "session_id": session.id,
                    "text": "Legacy citation",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(payload.keys()), {"type", "data", "text"})
        self.assertEqual(payload["type"], "citation_report")
        self.assertEqual(payload["text"], "One citation verified.")
        self.assertEqual(len(payload["data"]), 1)
        self.assertNotIn("summary", payload)
        self.assertNotIn("results", payload)
        self.assertNotIn("index", payload["data"][0])
        self.assertNotIn("raw_citation", payload["data"][0])
        self.assertNotIn("ux_group", payload["data"][0])

        db = self.db()
        try:
            persisted = db.query(ChatMessage).filter(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at).all()
            self.assertEqual(len(persisted), 2)
            self.assertEqual(persisted[-1].message_type, MessageType.CITATION_REPORT)
            self.assertEqual(persisted[-1].tool_results["summary"]["total_count"], 1)
            self.assertEqual(persisted[-1].tool_results["results"][0]["ux_group"], "verified")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
