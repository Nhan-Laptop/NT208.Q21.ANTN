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
    ReferenceMetadata,
    _normalize_semantic_scholar_paper,
    build_csl_json,
    build_completed_metadata,
    format_apa_reference,
    format_bibtex,
    parse_reference_metadata,
    search_semantic_scholar_candidates,
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


class _CitationTestSettings:
    def __init__(
        self,
        *,
        semantic_scholar_enabled: bool = False,
        semantic_scholar_api_key: str | None = None,
        semantic_scholar_fallback_threshold: float = 0.90,
    ) -> None:
        self.semantic_scholar_enabled = semantic_scholar_enabled
        self.semantic_scholar_api_key = semantic_scholar_api_key
        self.semantic_scholar_fallback_threshold = semantic_scholar_fallback_threshold


class CitationMetadataMatchingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings_patch = patch(
            "app.services.tools.citation_checker.get_settings",
            return_value=_CitationTestSettings(semantic_scholar_enabled=False),
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

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
        self.assertIsNotNone(r.completed_metadata)
        self.assertEqual(r.completed_metadata["doi"], "10.5555/attention")
        self.assertIn("Attention is all you need", r.formatted_apa or "")
        self.assertIn("doi = {10.5555/attention}", r.formatted_bibtex or "")

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
            title="Attention is all you need!",  # very close, but not title+year deduped
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
    # 8. Both APIs fail → UNVERIFIED with diagnostics, no fake data       #
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
        self.assertEqual(r.status, "UNVERIFIED")
        self.assertIsNotNone(r.warning)
        self.assertIsNone(r.matched_doi)
        self.assertIsNone(r.matched_title)
        self.assertEqual(r.candidates, [])
        self.assertEqual(r.source_diagnostics["crossref"]["state"], "error")
        self.assertEqual(r.source_diagnostics["openalex"]["state"], "error")
        self.assertTrue(r.search_attempted)

    # ------------------------------------------------------------------ #
    # 9. Candidate without DOI must not synthesize DOI or DOI URL         #
    # ------------------------------------------------------------------ #
    def test_no_doi_candidate_does_not_fabricate_doi(self) -> None:
        checker = CitationChecker()
        with (
            patch(
                "app.services.tools.citation_checker.search_crossref_candidates",
                return_value=[_attn_candidate("crossref", doi=None)],
            ),
            patch(
                "app.services.tools.citation_checker.search_openalex_candidates",
                return_value=[],
            ),
        ):
            results = checker.verify(APA_NO_DOI_REAL)

        r = [item for item in results if item.verification_mode == "metadata_match"][0]
        self.assertIsNone(r.matched_doi)
        self.assertIsNotNone(r.completed_metadata)
        self.assertNotIn("doi", r.completed_metadata)
        self.assertNotIn("doi =", (r.formatted_bibtex or "").lower())
        self.assertNotIn("https://doi.org", r.formatted_apa or "")

    # ------------------------------------------------------------------ #
    # 10. Formatters tolerate missing authors/year                        #
    # ------------------------------------------------------------------ #
    def test_formatters_missing_author_year_do_not_crash(self) -> None:
        metadata = {"title": "Metadata matching without complete fields", "source": "crossref", "type": "misc"}

        apa = format_apa_reference(metadata)
        bibtex = format_bibtex(metadata)
        csl = build_csl_json(metadata)

        self.assertIn("Metadata matching without complete fields", apa)
        self.assertIn("@misc", bibtex)
        self.assertEqual(csl["title"], "Metadata matching without complete fields")

    # ------------------------------------------------------------------ #
    # 11. BibTeX key is deterministic                                     #
    # ------------------------------------------------------------------ #
    def test_bibtex_key_is_deterministic(self) -> None:
        metadata = build_completed_metadata(_attn_candidate("crossref"), confidence=0.99)

        first = format_bibtex(metadata)
        second = format_bibtex(metadata)

        self.assertEqual(first, second)
        self.assertIn("@article{vaswani2017attentionisall", first)

    # ------------------------------------------------------------------ #
    # 12. Semantic Scholar normalize full paper                           #
    # ------------------------------------------------------------------ #
    def test_semantic_scholar_normalize_full_paper(self) -> None:
        paper = {
            "paperId": "abc123",
            "url": "https://www.semanticscholar.org/paper/abc123",
            "title": "A Semantic Scholar Test Paper",
            "authors": [{"authorId": "1", "name": "Ada Lovelace"}],
            "year": 2024,
            "venue": "Test Conference",
            "externalIds": {"DOI": "10.1234/TEST"},
            "publicationTypes": ["Conference"],
        }

        cand = _normalize_semantic_scholar_paper(paper)

        self.assertIsNotNone(cand)
        assert cand is not None
        self.assertEqual(cand.source, "semantic_scholar")
        self.assertEqual(cand.title, "A Semantic Scholar Test Paper")
        self.assertEqual(cand.authors, ["Ada Lovelace"])
        self.assertEqual(cand.year, 2024)
        self.assertEqual(cand.venue, "Test Conference")
        self.assertEqual(cand.doi, "10.1234/test")
        self.assertEqual(cand.external_id, "abc123")
        self.assertEqual(cand.external_id_type, "semantic_scholar")

    # ------------------------------------------------------------------ #
    # 13. Semantic Scholar missing DOI does not fabricate DOI             #
    # ------------------------------------------------------------------ #
    def test_semantic_scholar_missing_doi_does_not_fabricate(self) -> None:
        cand = _normalize_semantic_scholar_paper({
            "paperId": "abc123",
            "url": "https://www.semanticscholar.org/paper/abc123",
            "title": "No DOI Paper",
            "authors": [{"name": "Ada Lovelace"}],
            "year": 2024,
            "venue": "Test Journal",
            "externalIds": {},
        })

        self.assertIsNotNone(cand)
        assert cand is not None
        self.assertIsNone(cand.doi)
        completed = build_completed_metadata(cand, confidence=0.95)
        self.assertNotIn("doi", completed)

    # ------------------------------------------------------------------ #
    # 14. Crossref/OpenAlex fail then Semantic Scholar is used            #
    # ------------------------------------------------------------------ #
    def test_crossref_openalex_fail_semantic_scholar_hit(self) -> None:
        checker = CitationChecker()

        def _boom(*_args, **_kwargs):
            raise httpx.RequestError("network down")

        semantic_candidate = _attn_candidate("semantic_scholar")
        semantic_candidate.external_id = "s2-attention"
        semantic_candidate.external_id_type = "semantic_scholar"
        with (
            patch(
                "app.services.tools.citation_checker.get_settings",
                return_value=_CitationTestSettings(semantic_scholar_enabled=True),
            ),
            patch("app.services.tools.citation_checker.search_crossref_candidates", side_effect=_boom),
            patch("app.services.tools.citation_checker.search_openalex_candidates", side_effect=_boom),
            patch(
                "app.services.tools.citation_checker.search_semantic_scholar_candidates",
                return_value=[semantic_candidate],
            ) as semantic_search,
        ):
            results = checker.verify(APA_NO_DOI_REAL)

        r = [item for item in results if item.verification_mode == "metadata_match"][0]
        self.assertTrue(semantic_search.called)
        self.assertEqual(r.source, "semantic_scholar")
        self.assertEqual(r.matched_title, "Attention is all you need")

    # ------------------------------------------------------------------ #
    # 15. Strong Crossref/OpenAlex score skips Semantic Scholar           #
    # ------------------------------------------------------------------ #
    def test_strong_crossref_openalex_score_skips_semantic_scholar(self) -> None:
        checker = CitationChecker()
        with (
            patch(
                "app.services.tools.citation_checker.get_settings",
                return_value=_CitationTestSettings(semantic_scholar_enabled=True),
            ),
            patch(
                "app.services.tools.citation_checker.search_crossref_candidates",
                return_value=[_attn_candidate("crossref")],
            ),
            patch(
                "app.services.tools.citation_checker.search_openalex_candidates",
                return_value=[],
            ),
            patch(
                "app.services.tools.citation_checker.search_semantic_scholar_candidates",
                side_effect=AssertionError("Semantic Scholar must not be called for strong matches"),
            ),
        ):
            results = checker.verify(APA_NO_DOI_REAL)

        r = [item for item in results if item.verification_mode == "metadata_match"][0]
        self.assertEqual(r.source, "crossref")

    # ------------------------------------------------------------------ #
    # 16. Low Crossref/OpenAlex score triggers Semantic Scholar           #
    # ------------------------------------------------------------------ #
    def test_low_crossref_openalex_score_triggers_semantic_scholar(self) -> None:
        checker = CitationChecker()
        weak = CandidateWork(
            source="crossref",
            title="A different paper about sequence models",
            authors=["smith"],
            year=2015,
            venue="Other Venue",
            doi="10.0000/weak",
        )
        semantic_candidate = _attn_candidate("semantic_scholar")
        semantic_candidate.external_id = "s2-attention"
        semantic_candidate.external_id_type = "semantic_scholar"
        with (
            patch(
                "app.services.tools.citation_checker.get_settings",
                return_value=_CitationTestSettings(semantic_scholar_enabled=True),
            ),
            patch("app.services.tools.citation_checker.search_crossref_candidates", return_value=[weak]),
            patch("app.services.tools.citation_checker.search_openalex_candidates", return_value=[]),
            patch(
                "app.services.tools.citation_checker.search_semantic_scholar_candidates",
                return_value=[semantic_candidate],
            ) as semantic_search,
        ):
            results = checker.verify(APA_NO_DOI_REAL)

        r = [item for item in results if item.verification_mode == "metadata_match"][0]
        self.assertTrue(semantic_search.called)
        self.assertEqual(r.source, "semantic_scholar")
        self.assertEqual(r.matched_doi, "10.5555/attention")

    # ------------------------------------------------------------------ #
    # 17. Low-confidence parse uses raw-title fallback search             #
    # ------------------------------------------------------------------ #
    def test_low_confidence_parse_uses_raw_title_fallback(self) -> None:
        checker = CitationChecker()
        weak_raw = "Siemens 2005 Connectivism Learning Theory Digital Age"
        weak_ref = ReferenceMetadata(raw=weak_raw, title=None, authors=["siemens"], year=2005, confidence=0.2)
        fallback_candidate = CandidateWork(
            source="crossref",
            title="Connectivism Learning Theory Digital Age",
            authors=["siemens"],
            year=2005,
            venue="Learning Journal",
        )

        with (
            patch("app.services.tools.citation_checker.parse_reference_metadata", return_value=weak_ref),
            patch(
                "app.services.tools.citation_checker.search_crossref_candidates",
                return_value=[fallback_candidate],
            ) as crossref_search,
            patch("app.services.tools.citation_checker.search_openalex_candidates", return_value=[]),
        ):
            r = checker._verify_metadata_match({
                "raw": weak_raw,
                "type": "apa_reference",
                "authors": ["siemens"],
                "year": 2005,
                "doi": None,
            })

        self.assertTrue(crossref_search.called)
        self.assertEqual(r.parse_status, "LOW_CONFIDENCE_FALLBACK_USED")
        self.assertEqual(r.search_strategy, "raw_title_fallback")
        self.assertTrue(r.search_attempted)
        self.assertIn(r.status, {"LIKELY_MATCH", "POSSIBLE_MATCH", "METADATA_VERIFIED"})

    # ------------------------------------------------------------------ #
    # 18. Likely match does not expose formatted citation exports         #
    # ------------------------------------------------------------------ #
    def test_likely_match_hides_formatted_outputs(self) -> None:
        checker = CitationChecker()
        title_year_ref = ReferenceMetadata(
            raw="Attention is all you need. 2017.",
            title="Attention is all you need",
            authors=[],
            year=2017,
            confidence=0.65,
        )
        title_year_candidate = CandidateWork(
            source="crossref",
            title="Attention is all you need",
            authors=[],
            year=2017,
        )

        with (
            patch("app.services.tools.citation_checker.parse_reference_metadata", return_value=title_year_ref),
            patch(
                "app.services.tools.citation_checker.search_crossref_candidates",
                return_value=[title_year_candidate],
            ),
            patch("app.services.tools.citation_checker.search_openalex_candidates", return_value=[]),
        ):
            r = checker._verify_metadata_match({
                "raw": "Attention is all you need. 2017.",
                "type": "apa_reference",
                "authors": [],
                "year": 2017,
                "doi": None,
            })

        self.assertEqual(r.status, "LIKELY_MATCH")
        self.assertIsNone(r.completed_metadata)
        self.assertIsNone(r.formatted_apa)
        self.assertIsNone(r.formatted_bibtex)
        self.assertIsNone(r.csl_json)

    # ------------------------------------------------------------------ #
    # 19. Semantic Scholar 429/timeout returns [] without crashing        #
    # ------------------------------------------------------------------ #
    def test_semantic_scholar_429_and_timeout_do_not_crash(self) -> None:
        parsed = parse_reference_metadata(APA_NO_DOI_REAL)

        class RateLimitClient:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def get(self, *_args, **_kwargs):
                return httpx.Response(429, request=httpx.Request("GET", "https://example.test"))

        class TimeoutClient(RateLimitClient):
            def get(self, *_args, **_kwargs):
                raise httpx.TimeoutException("timeout")

        with patch(
            "app.services.tools.citation_checker.get_settings",
            return_value=_CitationTestSettings(semantic_scholar_enabled=True),
        ):
            with patch("app.services.tools.citation_checker.httpx.Client", RateLimitClient):
                self.assertEqual(search_semantic_scholar_candidates(parsed), [])
            with patch("app.services.tools.citation_checker.httpx.Client", TimeoutClient):
                self.assertEqual(search_semantic_scholar_candidates(parsed), [])


if __name__ == "__main__":
    unittest.main()
