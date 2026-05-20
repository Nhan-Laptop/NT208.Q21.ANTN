"""Tests for no-DOI metadata-matching citation verification.

Covers the new path in CitationChecker.verify():
- DOI input still uses verify_doi_exact (regression).
- Non-DOI references with title/author/year route through
  parse_reference_metadata -> search_crossref_candidates + search_openalex_candidates
  -> choose_best_match -> CitationCheckResult mapping.

External API calls are patched at the module-level so no network traffic occurs.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from app.services.tools.citation_checker import (
    CandidateWork,
    CitationChecker,
    CitationCheckResult,
)


APA_NO_DOI_REAL = (
    "Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., "
    "Kaiser, L., & Polosukhin, I. (2017). Attention is all you need. "
    "Advances in Neural Information Processing Systems, 30, 5998-6008."
)

IEEE_NO_DOI_REAL = (
    '[1] A. Vaswani, N. Shazeer, N. Parmar, J. Uszkoreit, L. Jones, A. Gomez, '
    'L. Kaiser, and I. Polosukhin, "Attention is all you need," '
    'in Advances in Neural Information Processing Systems, 2017, pp. 5998-6008.'
)


def _attn_candidate(source: str, *, doi: str | None = "10.5555/attention", year: int = 2017) -> CandidateWork:
    return CandidateWork(
        source=source,
        title="Attention is all you need",
        authors=["vaswani", "shazeer", "parmar", "uszkoreit", "jones", "gomez", "kaiser", "polosukhin"],
        year=year,
        venue="Advances in Neural Information Processing Systems",
        doi=doi,
        volume="30",
        pages="5998-6008",
    )


class CitationMetadataMatchingTest(unittest.TestCase):
    # ------------------------------------------------------------------ #
    # 1. DOI valid path still works                                       #
    # ------------------------------------------------------------------ #
    def test_doi_valid_path_still_works(self) -> None:
        checker = CitationChecker()
        verified = CitationCheckResult(
            citation="10.1038/s41586-020-2649-2",
            status="DOI_VERIFIED",
            doi="10.1038/s41586-020-2649-2",
            title="Array programming with NumPy",
            source="crossref",
            confidence=1.0,
        )
        with patch.object(checker, "_verify_doi_crossref", return_value=verified):
            results = checker.verify("https://doi.org/10.1038/s41586-020-2649-2")

        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.status, "DOI_VERIFIED")
        self.assertEqual(r.verification_mode, "doi")
        self.assertEqual(r.input_doi, "10.1038/s41586-020-2649-2")
        self.assertEqual(r.matched_doi, "10.1038/s41586-020-2649-2")
        self.assertEqual(r.matched_title, "Array programming with NumPy")

    # ------------------------------------------------------------------ #
    # 2. APA no-DOI real ref → METADATA_VERIFIED or LIKELY_MATCH          #
    # ------------------------------------------------------------------ #
    def test_apa_no_doi_real_reference_metadata_verified(self) -> None:
        checker = CitationChecker()
        with (
            patch(
                "app.services.tools.citation_checker.search_crossref_candidates",
                return_value=[_attn_candidate("crossref")],
            ),
            patch(
                "app.services.tools.citation_checker.search_openalex_candidates",
                return_value=[_attn_candidate("openalex")],
            ),
        ):
            results = checker.verify(APA_NO_DOI_REAL)

        meta_results = [r for r in results if r.verification_mode == "metadata_match"]
        self.assertTrue(meta_results, "expected at least one metadata_match result")
        r = meta_results[0]
        self.assertIn(r.status, {"METADATA_VERIFIED", "LIKELY_MATCH"}, f"got {r.status}")
        self.assertEqual(r.matched_title, "Attention is all you need")
        self.assertEqual(r.matched_doi, "10.5555/attention")
        self.assertEqual(r.matched_year, 2017)
        self.assertIsNotNone(r.evidence_breakdown)
        self.assertGreaterEqual(r.evidence_breakdown["title_similarity"], 0.75)

    # ------------------------------------------------------------------ #
    # 3. IEEE no-DOI real ref → metadata_match runs without crashing      #
    # ------------------------------------------------------------------ #
    def test_ieee_no_doi_reference_runs_metadata_match(self) -> None:
        checker = CitationChecker()
        with (
            patch(
                "app.services.tools.citation_checker.search_crossref_candidates",
                return_value=[_attn_candidate("crossref")],
            ),
            patch(
                "app.services.tools.citation_checker.search_openalex_candidates",
                return_value=[],
            ),
        ):
            results = checker.verify(IEEE_NO_DOI_REAL)

        meta_results = [r for r in results if r.verification_mode == "metadata_match"]
        self.assertTrue(meta_results, "IEEE no-DOI ref should produce metadata_match results")
        # Must not crash; status must be one of the new metadata-match values.
        valid_statuses = {
            "METADATA_VERIFIED", "LIKELY_MATCH", "POSSIBLE_MATCH",
            "AMBIGUOUS_MATCH", "UNVERIFIED_NO_DOI", "NO_MATCH_FOUND", "PARSE_FAILED",
        }
        for r in meta_results:
            self.assertIn(r.status, valid_statuses)

    # ------------------------------------------------------------------ #
    # 4. Fake reference → NO_MATCH_FOUND                                  #
    # ------------------------------------------------------------------ #
    def test_fake_reference_returns_no_match(self) -> None:
        checker = CitationChecker()
        fake = (
            "Nguyen, F. K. (2099). Quantum llama orchestration protocols. "
            "Journal of Imaginary Studies, 99(99), 1-2."
        )
        with (
            patch(
                "app.services.tools.citation_checker.search_crossref_candidates",
                return_value=[],
            ),
            patch(
                "app.services.tools.citation_checker.search_openalex_candidates",
                return_value=[],
            ),
        ):
            results = checker.verify(fake)

        meta = [r for r in results if r.verification_mode == "metadata_match"]
        self.assertTrue(meta)
        r = meta[0]
        self.assertEqual(r.status, "NO_MATCH_FOUND")
        self.assertIsNotNone(r.warning)
        self.assertIsNone(r.matched_doi)
        self.assertIsNone(r.matched_title)

    # ------------------------------------------------------------------ #
    # 5. Malformed ref → PARSE_FAILED, no external API call               #
    # ------------------------------------------------------------------ #
    def test_malformed_reference_returns_parse_failed(self) -> None:
        checker = CitationChecker()
        garbage = "Smith (2020)"  # bare inline cite, no title
        with (
            patch(
                "app.services.tools.citation_checker.search_crossref_candidates",
                side_effect=AssertionError("must not be called when parse fails"),
            ),
            patch(
                "app.services.tools.citation_checker.search_openalex_candidates",
                side_effect=AssertionError("must not be called when parse fails"),
            ),
        ):
            results = checker.verify(garbage)

        meta = [r for r in results if r.verification_mode == "metadata_match"]
        self.assertTrue(meta)
        self.assertTrue(all(r.status == "PARSE_FAILED" for r in meta))

    # ------------------------------------------------------------------ #
    # 6. Ambiguous candidates → AMBIGUOUS_MATCH                           #
    # ------------------------------------------------------------------ #
    def test_ambiguous_candidates_returns_ambiguous_match(self) -> None:
        checker = CitationChecker()
        # Two candidates with VERY close scores (full author / venue match,
        # title differs by one trailing char so gap < 0.05 but top1 >= 0.65).
        full_authors = [
            "vaswani", "shazeer", "parmar", "uszkoreit",
            "jones", "gomez", "kaiser", "polosukhin",
        ]
        venue = "Advances in Neural Information Processing Systems"
        cand_a = CandidateWork(
            source="crossref",
            title="Attention is all you need",
            authors=list(full_authors),
            year=2017,
            venue=venue,
            doi="10.0001/a",
        )
        cand_b = CandidateWork(
            source="openalex",
            title="Attention is all you need.",  # one trailing dot
            authors=list(full_authors),
            year=2017,
            venue=venue,
            doi="10.0001/b",
        )
        with (
            patch(
                "app.services.tools.citation_checker.search_crossref_candidates",
                return_value=[cand_a],
            ),
            patch(
                "app.services.tools.citation_checker.search_openalex_candidates",
                return_value=[cand_b],
            ),
        ):
            results = checker.verify(APA_NO_DOI_REAL)

        meta = [r for r in results if r.verification_mode == "metadata_match"]
        self.assertTrue(meta)
        # At least one should be AMBIGUOUS_MATCH because gap is < 0.05.
        self.assertTrue(any(r.status == "AMBIGUOUS_MATCH" for r in meta))

    # ------------------------------------------------------------------ #
    # 7. Crossref fails but OpenAlex returns result → no crash, OA result #
    # ------------------------------------------------------------------ #
    def test_crossref_fails_but_openalex_returns_result(self) -> None:
        checker = CitationChecker()

        def _crossref_boom(*_args, **_kwargs):
            raise httpx.RequestError("crossref boom")

        with (
            patch(
                "app.services.tools.citation_checker.search_crossref_candidates",
                side_effect=_crossref_boom,
            ),
            patch(
                "app.services.tools.citation_checker.search_openalex_candidates",
                return_value=[_attn_candidate("openalex")],
            ),
        ):
            results = checker.verify(APA_NO_DOI_REAL)

        meta = [r for r in results if r.verification_mode == "metadata_match"]
        self.assertTrue(meta, "non-empty metadata_match results expected")
        r = meta[0]
        self.assertIn(r.status, {"METADATA_VERIFIED", "LIKELY_MATCH"})
        self.assertEqual(r.source, "openalex")
        self.assertEqual(r.matched_doi, "10.5555/attention")

    # ------------------------------------------------------------------ #
    # 8. Both APIs fail → NO_MATCH_FOUND with warning, no fake data       #
    # ------------------------------------------------------------------ #
    def test_both_apis_fail_returns_warning_no_fake_data(self) -> None:
        checker = CitationChecker()

        def _boom(*_args, **_kwargs):
            raise httpx.RequestError("network down")

        with (
            patch(
                "app.services.tools.citation_checker.search_crossref_candidates",
                side_effect=_boom,
            ),
            patch(
                "app.services.tools.citation_checker.search_openalex_candidates",
                side_effect=_boom,
            ),
        ):
            results = checker.verify(APA_NO_DOI_REAL)

        meta = [r for r in results if r.verification_mode == "metadata_match"]
        self.assertTrue(meta)
        r = meta[0]
        self.assertEqual(r.status, "NO_MATCH_FOUND")
        self.assertIsNotNone(r.warning)
        self.assertIsNone(r.matched_doi)
        self.assertIsNone(r.matched_title)
        self.assertEqual(r.candidates, [])


if __name__ == "__main__":
    unittest.main()
