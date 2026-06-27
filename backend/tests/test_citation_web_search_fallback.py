from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import httpx

from app.services.tools.citation_checker import CandidateWork, CitationCheckResult, CitationChecker


APA_NO_DOI_REAL = (
    "Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., "
    "Kaiser, L., & Polosukhin, I. (2017). Attention is all you need. "
    "Advances in Neural Information Processing Systems, 30, 5998-6008."
)


class _CitationTestSettings:
    def __init__(
        self,
        *,
        semantic_scholar_enabled: bool = False,
        semantic_scholar_api_key: str | None = None,
        semantic_scholar_fallback_threshold: float = 0.90,
        web_search_provider: str | None = "generic_json",
        web_search_api_key: str | None = "test-key",
        web_search_endpoint: str | None = "https://search.example.test",
        external_search_timeout_seconds: float = 5.0,
        tavily_api_key: str | None = "tvly-test-key",
        tavily_search_endpoint: str = "https://api.tavily.com/search",
        tavily_search_depth: str = "basic",
        tavily_max_results: int = 5,
        tavily_include_answer: bool = False,
        tavily_include_raw_content: bool = False,
        tavily_timeout_seconds: float = 8.0,
    ) -> None:
        self.semantic_scholar_enabled = semantic_scholar_enabled
        self.semantic_scholar_api_key = semantic_scholar_api_key
        self.semantic_scholar_fallback_threshold = semantic_scholar_fallback_threshold
        self.web_search_provider = web_search_provider
        self.web_search_api_key = web_search_api_key
        self.web_search_endpoint = web_search_endpoint
        self.external_search_timeout_seconds = external_search_timeout_seconds
        self.tavily_api_key = tavily_api_key
        self.tavily_search_endpoint = tavily_search_endpoint
        self.tavily_search_depth = tavily_search_depth
        self.tavily_max_results = tavily_max_results
        self.tavily_include_answer = tavily_include_answer
        self.tavily_include_raw_content = tavily_include_raw_content
        self.tavily_timeout_seconds = tavily_timeout_seconds


class _MockResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class CitationWebSearchFallbackTest(unittest.TestCase):
    def _citation(self) -> dict[str, object]:
        return {
            "raw": APA_NO_DOI_REAL,
            "type": "apa_reference",
            "authors": ["vaswani"],
            "year": 2017,
            "doi": None,
        }

    def test_web_search_doi_is_reverified_before_promotion(self) -> None:
        checker = CitationChecker()
        web_hit = CandidateWork(
            source="web_search",
            title="Attention is all you need",
            doi="10.5555/attention",
            url="https://example.org/attention",
            evidence_urls=["https://example.org/attention"],
            source_domain="example.org",
            raw={
                "snippet": "Attention is all you need DOI 10.5555/attention",
                "doi_candidates": ["10.5555/attention"],
            },
        )
        doi_verified = CitationCheckResult(
            citation="10.5555/attention",
            status="DOI_VERIFIED",
            doi="10.5555/attention",
            title="Attention is all you need",
            authors=["Ashish Vaswani"],
            year=2017,
            source="crossref_doi",
            confidence=1.0,
            verification_mode="doi",
            matched_doi="10.5555/attention",
            matched_title="Attention is all you need",
            resolver_chain=["crossref_exact"],
            matched_by="doi_exact",
            evidence_urls=["https://doi.org/10.5555/attention"],
            source_diagnostics={
                "crossref": {"state": "matched", "candidate_count": 1, "detail": None},
            },
        )

        with (
            patch("app.services.tools.citation_checker.get_settings", return_value=_CitationTestSettings()),
            patch("app.services.tools.citation_checker.search_crossref_candidates", return_value=[]),
            patch("app.services.tools.citation_checker.search_openalex_candidates", return_value=[]),
            patch.object(checker._datacite_source, "search", return_value=[]),
            patch.object(
                checker._web_search_source,
                "search_with_context",
                return_value=(
                    [web_hit],
                    {
                        "state": "matched",
                        "detail": None,
                        "query": "\"Attention is all you need\" vaswani 2017 DOI",
                        "provider": "generic_json",
                    },
                ),
            ),
            patch.object(checker, "verify_doi_exact", return_value=doi_verified) as verify_doi_exact,
        ):
            result = checker._verify_metadata_match(self._citation())

        verify_doi_exact.assert_called_once()
        self.assertEqual(result.status, "DOI_VERIFIED")
        self.assertEqual(result.discovered_from, "web_search")
        self.assertEqual(result.source_domain, "example.org")
        self.assertEqual(result.web_search_provider, "generic_json")
        self.assertEqual(result.web_search_query, "\"Attention is all you need\" vaswani 2017 DOI")
        self.assertIn("https://example.org/attention", result.evidence_urls)
        self.assertIn("web_search", result.resolver_chain)
        self.assertEqual(result.source_diagnostics["web_search"]["state"], "matched")

    def test_tavily_doi_is_reverified_before_promotion(self) -> None:
        checker = CitationChecker()
        doi_verified = CitationCheckResult(
            citation="10.5555/attention",
            status="DOI_VERIFIED",
            doi="10.5555/attention",
            title="Attention is all you need",
            authors=["Ashish Vaswani"],
            year=2017,
            source="crossref_doi",
            confidence=1.0,
            verification_mode="doi",
            matched_doi="10.5555/attention",
            matched_title="Attention is all you need",
            resolver_chain=["crossref_exact"],
            matched_by="doi_exact",
            evidence_urls=["https://doi.org/10.5555/attention"],
            source_diagnostics={
                "crossref": {"state": "matched", "candidate_count": 1, "detail": None},
            },
        )
        client_cm = MagicMock()
        client = MagicMock()
        client_cm.__enter__.return_value = client
        client_cm.__exit__.return_value = False
        client.post.return_value = _MockResponse(
            200,
            {
                "results": [
                    {
                        "title": "Attention is all you need",
                        "url": "https://example.org/attention",
                        "content": "Conference page DOI 10.5555/attention",
                        "score": 0.93,
                        "source": "example.org",
                    }
                ]
            },
        )

        with (
            patch(
                "app.services.tools.citation_checker.get_settings",
                return_value=_CitationTestSettings(web_search_provider="tavily"),
            ),
            patch("app.services.tools.citation_checker.search_crossref_candidates", return_value=[]),
            patch("app.services.tools.citation_checker.search_openalex_candidates", return_value=[]),
            patch.object(checker._datacite_source, "search", return_value=[]),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", return_value=client_cm),
            patch.object(checker, "verify_doi_exact", return_value=doi_verified) as verify_doi_exact,
        ):
            result = checker._verify_metadata_match(self._citation())

        verify_doi_exact.assert_called_once()
        client.post.assert_called_once()
        self.assertEqual(result.status, "DOI_VERIFIED")
        self.assertEqual(result.discovered_from, "web_search")
        self.assertEqual(result.web_search_provider, "tavily")
        self.assertEqual(result.web_search_query, "\"Attention is all you need\" vaswani 2017 DOI")
        self.assertIn("https://example.org/attention", result.evidence_urls)

    def test_web_search_url_only_does_not_become_metadata_verified(self) -> None:
        checker = CitationChecker()
        web_hit = CandidateWork(
            source="web_search",
            title="Attention is all you need",
            url="https://publisher.example.org/attention",
            evidence_urls=["https://publisher.example.org/attention"],
            source_domain="publisher.example.org",
            raw={"snippet": "Conference paper landing page"},
        )

        with (
            patch("app.services.tools.citation_checker.get_settings", return_value=_CitationTestSettings()),
            patch("app.services.tools.citation_checker.search_crossref_candidates", return_value=[]),
            patch("app.services.tools.citation_checker.search_openalex_candidates", return_value=[]),
            patch.object(checker._datacite_source, "search", return_value=[]),
            patch.object(
                checker._web_search_source,
                "search_with_context",
                return_value=(
                    [web_hit],
                    {
                        "state": "matched",
                        "detail": None,
                        "query": "\"Attention is all you need\" vaswani",
                        "provider": "generic_json",
                    },
                ),
            ),
        ):
            result = checker._verify_metadata_match(self._citation())

        self.assertIn(result.status, {"POSSIBLE_MATCH", "LIKELY_MATCH"})
        self.assertNotEqual(result.status, "METADATA_VERIFIED")
        self.assertEqual(result.discovered_from, "web_search")
        self.assertIn("https://publisher.example.org/attention", result.evidence_urls)
        self.assertIn("Web search surfaced a similar result", result.warning or "")

    def test_fake_explicit_doi_does_not_trigger_web_search(self) -> None:
        checker = CitationChecker()

        with (
            patch.object(checker, "_verify_doi_crossref", return_value=None),
            patch.object(checker, "_verify_doi_datacite_exact", return_value=None),
            patch.object(checker, "_verify_doi_openalex_exact", return_value=None),
            patch.object(
                checker._web_search_source,
                "search_with_context",
                side_effect=AssertionError("web search must not run for exact DOI input"),
            ),
        ):
            results = checker.verify("doi:10.1234/fake-doi")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "DOI_NOT_FOUND")

    def test_missing_web_search_api_key_skips_gracefully(self) -> None:
        checker = CitationChecker()
        settings = _CitationTestSettings(web_search_api_key=None)

        with (
            patch("app.services.tools.citation_checker.get_settings", return_value=settings),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", side_effect=AssertionError("HTTP must not run without API key")),
            patch("app.services.tools.citation_checker.search_crossref_candidates", return_value=[]),
            patch("app.services.tools.citation_checker.search_openalex_candidates", return_value=[]),
            patch.object(checker._datacite_source, "search", return_value=[]),
        ):
            result = checker._verify_metadata_match(self._citation())

        self.assertEqual(result.status, "NO_MATCH_FOUND")
        self.assertEqual(result.source_diagnostics["web_search"]["state"], "disabled")
        self.assertIn("WEB_SEARCH_API_KEY", result.source_diagnostics["web_search"]["detail"] or "")
        self.assertIn("WEB_SEARCH_API_KEY", result.web_search_skipped_reason or "")

    def test_tavily_error_keeps_citation_verification_graceful(self) -> None:
        checker = CitationChecker()
        request = httpx.Request("POST", "https://api.tavily.com/search")
        client_cm = MagicMock()
        client = MagicMock()
        client_cm.__enter__.return_value = client
        client_cm.__exit__.return_value = False
        client.post.side_effect = httpx.RequestError("network failure", request=request)

        with (
            patch(
                "app.services.tools.citation_checker.get_settings",
                return_value=_CitationTestSettings(web_search_provider="tavily"),
            ),
            patch("app.services.tools.citation_checker.search_crossref_candidates", return_value=[]),
            patch("app.services.tools.citation_checker.search_openalex_candidates", return_value=[]),
            patch.object(checker._datacite_source, "search", return_value=[]),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", return_value=client_cm),
        ):
            result = checker._verify_metadata_match(self._citation())

        self.assertEqual(result.status, "UNVERIFIED")
        self.assertEqual(result.source_diagnostics["web_search"]["state"], "error")
        self.assertIn("network failure", result.source_diagnostics["web_search"]["detail"] or "")

    def test_tavily_rate_limit_keeps_citation_verification_graceful(self) -> None:
        checker = CitationChecker()
        client_cm = MagicMock()
        client = MagicMock()
        client_cm.__enter__.return_value = client
        client_cm.__exit__.return_value = False
        client.post.return_value = _MockResponse(429, {"detail": "rate limited"})

        with (
            patch(
                "app.services.tools.citation_checker.get_settings",
                return_value=_CitationTestSettings(web_search_provider="tavily"),
            ),
            patch("app.services.tools.citation_checker.search_crossref_candidates", return_value=[]),
            patch("app.services.tools.citation_checker.search_openalex_candidates", return_value=[]),
            patch.object(checker._datacite_source, "search", return_value=[]),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", return_value=client_cm),
        ):
            result = checker._verify_metadata_match(self._citation())

        self.assertEqual(result.status, "UNVERIFIED")
        self.assertEqual(result.source_diagnostics["web_search"]["state"], "rate_limited")
        self.assertEqual(result.source_diagnostics["web_search"]["detail"], "HTTP 429 (rate limited).")

    def test_multiple_web_dois_do_not_get_auto_promoted(self) -> None:
        checker = CitationChecker()
        web_hit_one = CandidateWork(
            source="web_search",
            title="Attention is all you need",
            url="https://example.org/attention-one",
            evidence_urls=["https://example.org/attention-one"],
            source_domain="example.org",
            raw={"doi_candidates": ["10.5555/attention-one"]},
        )
        web_hit_two = CandidateWork(
            source="web_search",
            title="Attention is all you need",
            url="https://example.net/attention-two",
            evidence_urls=["https://example.net/attention-two"],
            source_domain="example.net",
            raw={"doi_candidates": ["10.5555/attention-two"]},
        )

        with (
            patch("app.services.tools.citation_checker.get_settings", return_value=_CitationTestSettings()),
            patch("app.services.tools.citation_checker.search_crossref_candidates", return_value=[]),
            patch("app.services.tools.citation_checker.search_openalex_candidates", return_value=[]),
            patch.object(checker._datacite_source, "search", return_value=[]),
            patch.object(
                checker._web_search_source,
                "search_with_context",
                return_value=(
                    [web_hit_one, web_hit_two],
                    {
                        "state": "matched",
                        "detail": None,
                        "query": "\"Attention is all you need\" DOI",
                        "provider": "generic_json",
                    },
                ),
            ),
            patch.object(
                checker,
                "verify_doi_exact",
                side_effect=AssertionError("ambiguous DOI hints must not trigger exact DOI verification"),
            ),
        ):
            result = checker._verify_metadata_match(self._citation())

        self.assertNotEqual(result.status, "DOI_VERIFIED")
        self.assertEqual(result.source_diagnostics["web_search"]["state"], "ambiguous")
        self.assertIn("Multiple distinct DOI hints", result.source_diagnostics["web_search"]["detail"] or "")


if __name__ == "__main__":
    unittest.main()
