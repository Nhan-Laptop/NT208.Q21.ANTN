from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from app.services import llm_service
from app.services.academic_policy import (
    CRAWLER_DB_NO_DATA_MESSAGE,
    format_crawler_record_summary,
)
from app.services.academic_verification_formatter import (
    format_citation_summary,
    format_retraction_summary,
)
from app.services.tools.citation_checker import CitationChecker, CitationCheckResult
from app.services.tools.retraction_scan import RetractionResult, RetractionScanner


class AcademicVerificationFlowTest(unittest.TestCase):
    def test_exact_doi_input_returns_verified_record(self) -> None:
        checker = CitationChecker()
        verified = CitationCheckResult(
            citation="10.1234/jis.2023.001",
            status="DOI_VERIFIED",
            doi="10.1234/jis.2023.001",
            title="Journal Integrity Study",
            source="crossref",
            confidence=1.0,
        )

        with patch.object(checker, "_verify_doi_crossref", return_value=verified) as crossref:
            results = checker.verify("https://doi.org/10.1234/JIS.2023.001")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "DOI_VERIFIED")
        self.assertEqual(results[0].doi, "10.1234/jis.2023.001")
        crossref.assert_called_once_with("10.1234/jis.2023.001")
        friendly = format_citation_summary(checker.get_statistics(results))
        self.assertIn("tìm thấy bản ghi học thuật khớp rõ ràng", friendly)
        self.assertNotIn("Đã xác minh 1 citation", friendly)

    def test_exact_doi_not_found_does_not_fall_back_to_fuzzy_partial_match(self) -> None:
        checker = CitationChecker()

        with (
            patch.object(checker, "_verify_doi_crossref", return_value=None),
            patch.object(checker, "_verify_doi_openalex_exact", return_value=None),
            patch.object(checker, "_verify_openalex", side_effect=AssertionError("fuzzy fallback should not run")),
        ):
            results = checker.verify("doi:10.1234/jis.2023.001")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "DOI_NOT_FOUND")
        self.assertEqual(results[0].doi, "10.1234/jis.2023.001")
        stats = checker.get_statistics(results)
        self.assertEqual(stats["doi_not_found"], 1)
        self.assertEqual(stats["partial_match"], 0)
        friendly = format_citation_summary(stats)
        self.assertIn("chưa tìm thấy bản ghi học thuật khớp hoàn toàn", friendly)
        self.assertIn("không dùng kết quả gần giống", friendly)

    def test_non_doi_citation_text_keeps_fuzzy_partial_match_path(self) -> None:
        checker = CitationChecker()
        partial = CitationCheckResult(
            citation="Smith (2023)",
            status="PARTIAL_MATCH",
            evidence="Possible match: nearby record",
            doi="10.5555/nearby",
            title="Nearby Record",
            confidence=0.5,
        )

        with patch.object(checker, "_verify_openalex", return_value=partial) as openalex:
            results = checker.verify("Smith (2023)")

        self.assertGreaterEqual(len(results), 1)
        self.assertTrue(all(result.status == "PARTIAL_MATCH" for result in results))
        self.assertGreaterEqual(openalex.call_count, 1)
        friendly = format_citation_summary(checker.get_statistics(results))
        self.assertIn("chỉ khớp một phần", friendly)
        self.assertIn("đối chiếu thêm DOI", friendly)

    def test_unresolved_doi_skips_retraction_scan_gracefully(self) -> None:
        scanner = RetractionScanner()
        unresolved = CitationCheckResult(
            citation="10.1234/jis.2023.001",
            status="DOI_NOT_FOUND",
            doi="10.1234/jis.2023.001",
            evidence="Exact DOI lookup did not resolve this identifier.",
        )

        with patch.object(scanner, "scan_doi", side_effect=AssertionError("scan_doi should not run")):
            results = scanner.scan_verified("10.1234/jis.2023.001", lambda _doi: unresolved)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "UNVERIFIED")
        self.assertTrue(results[0].scan_skipped)
        self.assertIsNotNone(results[0].skip_reason)
        self.assertIn("bước kiểm tra retraction được bỏ qua", results[0].risk_factors[0])
        summary = scanner.get_summary(results)
        self.assertEqual(summary["total_checked"], 0)
        self.assertEqual(summary["unresolved"], 1)
        self.assertTrue(summary["scan_skipped"])
        self.assertFalse(summary["no_doi_found"])
        friendly = format_retraction_summary(summary)
        self.assertIn("bước kiểm tra retraction cũng được bỏ qua", friendly)
        self.assertNotIn("Invalid", friendly)

    def test_retraction_scan_error_does_not_store_raw_internal_exception_for_users(self) -> None:
        scanner = RetractionScanner()

        with patch.object(scanner, "scan_doi", side_effect=RuntimeError("database socket exploded")):
            results = scanner.scan("10.1234/jis.2023.001")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "ERROR")
        self.assertIn("chưa hoàn tất", results[0].risk_factors[0])
        self.assertNotIn("database socket exploded", results[0].risk_factors[0])

    def test_resolved_doi_runs_retraction_scan_with_verified_identifier(self) -> None:
        scanner = RetractionScanner()
        resolved = CitationCheckResult(
            citation="10.1234/JIS.2023.001",
            status="DOI_VERIFIED",
            doi="10.1234/jis.2023.001",
            title="Journal Integrity Study",
        )
        active = RetractionResult(
            doi="10.1234/jis.2023.001",
            status="ACTIVE",
            title="Journal Integrity Study",
        )

        with patch.object(scanner, "scan_doi", return_value=active) as scan_doi:
            results = scanner.scan_verified("10.1234/JIS.2023.001", lambda _doi: resolved)

        self.assertEqual(results, [active])
        scan_doi.assert_called_once_with("10.1234/jis.2023.001")
        summary = scanner.get_summary(results)
        self.assertEqual(summary["total_checked"], 1)
        self.assertEqual(summary["active"], 1)
        friendly = format_retraction_summary(summary)
        self.assertIn("chưa thấy tín hiệu đáng lo ngại", friendly)
        self.assertNotIn("Retraction & PubPeer Scan", friendly)

    def test_tool_executor_coerces_doi_like_document_id_to_text_for_retraction(self) -> None:
        doi = "10.1234/jis.2023.001"
        original = llm_service._TOOL_FUNCTIONS["scan_retraction_and_pubpeer"]
        fake_tool = Mock(return_value={
            "results": [],
            "summary": {
                "total_checked": 0,
                "no_doi_found": False,
                "unresolved": 1,
                "scan_skipped": True,
            },
            "received": doi,
        })
        llm_service._TOOL_FUNCTIONS["scan_retraction_and_pubpeer"] = fake_tool
        try:
            result = llm_service._execute_tool_call(
                "scan_retraction_and_pubpeer",
                {"document_id": doi},
                allowed_document_ids=set(),
            )
        finally:
            llm_service._TOOL_FUNCTIONS["scan_retraction_and_pubpeer"] = original

        self.assertNotIn("error", result)
        fake_tool.assert_called_once_with(text=doi)

    def test_tool_state_text_uses_user_safe_error_for_internal_failure(self) -> None:
        text = llm_service._build_tool_state_text(
            "scan_retraction_and_pubpeer",
            {"error": "Invalid document_id: 10.1234/jis.2023.001"},
        )

        self.assertIsNotNone(text)
        self.assertIn("tham chiếu tài liệu không hợp lệ", text or "")
        self.assertNotIn("Invalid document_id", text or "")

    def test_system_prompt_contains_grounded_crawler_db_policy(self) -> None:
        prompt = llm_service._build_system_prompt({"verify_citation"}, set())

        self.assertIn("retrieve first, reason second, answer last", prompt)
        self.assertIn("corpus học thuật đã xác minh", prompt)
        self.assertIn("DOI input phải resolve exact trước", prompt)
        self.assertIn("Không lộ lỗi thô", prompt)

    def test_crawler_db_record_summary_is_grounded_and_has_no_data_fallback(self) -> None:
        empty = format_crawler_record_summary({})
        self.assertEqual(empty, CRAWLER_DB_NO_DATA_MESSAGE)

        summary = format_crawler_record_summary({
            "title": "Grounded Retrieval for Academic Matching",
            "abstract": "This paper studies retrieval and reranking for venue recommendation.",
            "keywords": ["retrieval", "reranking"],
            "venue": "AIRA Journal",
            "publication_year": 2026,
            "doi": "10.1234/aira.2026.001",
        })

        self.assertIn("Tóm tắt từ abstract", summary)
        self.assertIn("retrieval and reranking", summary)
        self.assertIn("Nguồn: Grounded Retrieval", summary)
        self.assertNotIn("state-of-the-art", summary.lower())


    def test_multi_author_apa_reference_with_doi_is_not_split_into_fragments(self) -> None:
        """Regression: APA 7 reference with many authors and a DOI at the end
        must NOT produce fragmentary citations from the middle of the author list."""
        apa_ref = (
            "Harris, C. R., Millman, K. J., van der Walt, S. J., Gommers, R., "
            "Virtanen, P., Cournapeau, D., Wieser, E., Taylor, J., Berg, S., "
            "Smith, N. J., Kern, R., Picus, M., Hoyer, S., van Kerkwijk, M. H., "
            "Brett, M., Haldane, A., del Río, J. F., Wiebe, M., Peterson, P., "
            "Gohlke, C., & Oliphant, T. E. (2020). Array programming with NumPy. "
            "Nature, 585(7825), 357–362. https://doi.org/10.1038/s41586-020-2649-2"
        )
        checker = CitationChecker()
        citations = checker.extract_citations(apa_ref)

        self.assertEqual(
            len(citations), 1,
            f"Expected exactly 1 citation (the DOI), got {len(citations)}",
        )
        self.assertEqual(citations[0]["type"], "doi")
        self.assertEqual(citations[0]["doi"], "10.1038/s41586-020-2649-2")

    def test_multi_author_apa_mixed_with_non_doi_reference_is_separate(self) -> None:
        """A non-DOI APA reference on a separate line from a DOI reference
        must still be extracted as a distinct citation."""
        text = (
            "Smith, J. A. (2019). Citation without DOI. Journal of Examples, 5(2), 100-110.\n\n"
            "Harris, C. R., ... Gohlke, C., & Oliphant, T. E. (2020). "
            "Array programming with NumPy. Nature, 585, 357–362. "
            "https://doi.org/10.1038/s41586-020-2649-2"
        )
        checker = CitationChecker()
        citations = checker.extract_citations(text)

        self.assertEqual(
            len(citations), 2,
            f"Expected 2 citations (DOI + APA), got {len(citations)}",
        )
        types = {c["type"] for c in citations}
        self.assertIn("doi", types)
        self.assertIn("apa_reference", types)


if __name__ == "__main__":
    unittest.main()
