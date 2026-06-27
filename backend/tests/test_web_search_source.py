from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.tools.citation.models import ReferenceMetadata
from app.services.tools.citation.sources.web_search import WebSearchSource


class _WebSearchSettings:
    def __init__(
        self,
        *,
        web_search_provider: str = "disabled",
        web_search_api_key: str | None = None,
        web_search_endpoint: str | None = None,
        external_search_timeout_seconds: float = 5.0,
        tavily_api_key: str | None = None,
        tavily_search_endpoint: str = "https://api.tavily.com/search",
        tavily_search_depth: str = "basic",
        tavily_max_results: int = 5,
        tavily_include_answer: bool = False,
        tavily_include_raw_content: bool = False,
        tavily_timeout_seconds: float = 8.0,
    ) -> None:
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
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _reference() -> ReferenceMetadata:
    return ReferenceMetadata(
        raw="Attention is all you need",
        title="Attention is all you need",
        authors=["vaswani"],
        year=2017,
        confidence=0.9,
    )


class WebSearchSourceTest(unittest.TestCase):
    def _client_context(self, *, method: str, response: _MockResponse | None = None, side_effect: Exception | None = None):
        client_cm = MagicMock()
        client = MagicMock()
        client_cm.__enter__.return_value = client
        client_cm.__exit__.return_value = False
        if side_effect is not None:
            getattr(client, method).side_effect = side_effect
        else:
            getattr(client, method).return_value = response
        return client_cm, client

    def test_generic_json_request_and_normalization(self) -> None:
        source = WebSearchSource()
        settings = _WebSearchSettings(
            web_search_provider="generic_json",
            web_search_api_key="generic-key",
            web_search_endpoint="https://search.example.test",
            external_search_timeout_seconds=6.5,
        )
        response = _MockResponse(
            200,
            {
                "results": [
                    {
                        "title": "Attention is all you need",
                        "url": "https://example.org/attention",
                        "snippet": "Conference paper DOI 10.5555/attention",
                        "source_domain": "example.org",
                        "score": 0.88,
                    }
                ]
            },
        )
        client_cm, client = self._client_context(method="get", response=response)

        with (
            patch("app.services.tools.citation.sources.web_search.get_settings", return_value=settings),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", return_value=client_cm) as client_factory,
        ):
            candidates, context = source.search_with_context(_reference(), limit=4)

        client_factory.assert_called_once_with(timeout=6.5)
        client.get.assert_called_once()
        _, kwargs = client.get.call_args
        self.assertEqual(kwargs["params"]["num"], 4)
        self.assertEqual(kwargs["params"]["q"], "\"Attention is all you need\" vaswani 2017 DOI")
        self.assertLessEqual(len(kwargs["params"]["q"]), 240)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer generic-key")
        self.assertEqual(context["state"], "matched")
        self.assertEqual(context["provider"], "generic_json")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].doi, "10.5555/attention")
        self.assertEqual(candidates[0].source_domain, "example.org")
        self.assertEqual(candidates[0].raw["score"], 0.88)

    def test_generic_json_malformed_results_payload_does_not_crash(self) -> None:
        source = WebSearchSource()
        settings = _WebSearchSettings(
            web_search_provider="generic_json",
            web_search_api_key="generic-key",
            web_search_endpoint="https://search.example.test",
        )
        response = _MockResponse(200, {"results": "not-a-list"})
        client_cm, _client = self._client_context(method="get", response=response)

        with (
            patch("app.services.tools.citation.sources.web_search.get_settings", return_value=settings),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", return_value=client_cm),
        ):
            candidates, context = source.search_with_context(_reference(), limit=4)

        self.assertEqual(candidates, [])
        self.assertEqual(context["state"], "error")
        self.assertIn("results must be a list", context["detail"] or "")

    def test_query_builder_truncates_long_metadata_before_provider_request(self) -> None:
        source = WebSearchSource()
        settings = _WebSearchSettings(
            web_search_provider="generic_json",
            web_search_api_key="generic-key",
            web_search_endpoint="https://search.example.test",
        )
        response = _MockResponse(200, {"results": []})
        client_cm, client = self._client_context(method="get", response=response)
        ref = ReferenceMetadata(
            raw="Long title citation",
            title="A" * 400,
            authors=["B" * 200],
            year=2017,
            confidence=0.9,
        )

        with (
            patch("app.services.tools.citation.sources.web_search.get_settings", return_value=settings),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", return_value=client_cm),
        ):
            _candidates, context = source.search_with_context(ref, limit=4)

        self.assertEqual(context["state"], "no_match")
        self.assertGreaterEqual(client.get.call_count, 1)
        query = client.get.call_args_list[0].kwargs["params"]["q"]
        self.assertLessEqual(len(query), 240)
        self.assertTrue(query.startswith("\""))
        self.assertNotIn("B" * 120, query)

    def test_tavily_request_and_normalization(self) -> None:
        source = WebSearchSource()
        settings = _WebSearchSettings(
            web_search_provider="tavily",
            tavily_api_key="tvly-test-key",
            tavily_max_results=6,
            tavily_timeout_seconds=9.0,
        )
        response = _MockResponse(
            200,
            {
                "results": [
                    {
                        "title": "Attention is all you need",
                        "url": "https://papers.example.org/attention",
                        "content": "Proceedings page with DOI 10.5555/attention",
                        "score": 0.91,
                        "source": "papers.example.org",
                        "favicon": "https://papers.example.org/favicon.ico",
                    }
                ]
            },
        )
        client_cm, client = self._client_context(method="post", response=response)

        with (
            patch("app.services.tools.citation.sources.web_search.get_settings", return_value=settings),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", return_value=client_cm) as client_factory,
        ):
            candidates, context = source.search_with_context(_reference(), limit=4)

        client_factory.assert_called_once_with(timeout=9.0)
        client.post.assert_called_once()
        args, kwargs = client.post.call_args
        self.assertEqual(args[0], "https://api.tavily.com/search")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tvly-test-key")
        self.assertEqual(kwargs["json"]["query"], "\"Attention is all you need\" vaswani 2017 DOI")
        self.assertEqual(kwargs["json"]["search_depth"], "basic")
        self.assertEqual(kwargs["json"]["max_results"], 4)
        self.assertFalse(kwargs["json"]["include_answer"])
        self.assertFalse(kwargs["json"]["include_raw_content"])
        self.assertEqual(context["state"], "matched")
        self.assertEqual(context["provider"], "tavily")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].doi, "10.5555/attention")
        self.assertEqual(candidates[0].raw["score"], 0.91)
        self.assertEqual(candidates[0].raw["favicon"], "https://papers.example.org/favicon.ico")
        self.assertEqual(candidates[0].source_domain, "papers.example.org")

    def test_tavily_missing_api_key_skips(self) -> None:
        source = WebSearchSource()
        settings = _WebSearchSettings(web_search_provider="tavily", tavily_api_key=None)

        with patch("app.services.tools.citation.sources.web_search.get_settings", return_value=settings):
            candidates, context = source.search_with_context(_reference(), limit=3)

        self.assertEqual(candidates, [])
        self.assertEqual(context["state"], "disabled")
        self.assertIn("TAVILY_API_KEY", context["detail"] or "")

    def test_author_publication_query_builder_uses_author_specific_queries(self) -> None:
        source = WebSearchSource()
        settings = _WebSearchSettings(
            web_search_provider="generic_json",
            web_search_api_key="generic-key",
            web_search_endpoint="https://search.example.test",
        )
        response = _MockResponse(200, {"results": []})
        client_cm, client = self._client_context(method="get", response=response)

        with (
            patch("app.services.tools.citation.sources.web_search.get_settings", return_value=settings),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", return_value=client_cm),
        ):
            candidates, context = source.search_author_publications_with_context(
                "Stefan van der Walt",
                source_title="Array programming with NumPy",
                limit=4,
            )

        self.assertEqual(candidates, [])
        self.assertEqual(context["state"], "no_match")
        self.assertGreaterEqual(client.get.call_count, 1)
        query = client.get.call_args_list[0].kwargs["params"]["q"]
        self.assertEqual(query, "\"Stefan van der Walt\" publications")

    def test_tavily_timeout_returns_timeout(self) -> None:
        source = WebSearchSource()
        settings = _WebSearchSettings(web_search_provider="tavily", tavily_api_key="tvly-test-key")
        client_cm, _client = self._client_context(
            method="post",
            side_effect=httpx.TimeoutException("timed out"),
        )

        with (
            patch("app.services.tools.citation.sources.web_search.get_settings", return_value=settings),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", return_value=client_cm),
        ):
            candidates, context = source.search_with_context(_reference(), limit=3)

        self.assertEqual(candidates, [])
        self.assertEqual(context["state"], "timeout")

    def test_tavily_network_error_returns_error(self) -> None:
        source = WebSearchSource()
        settings = _WebSearchSettings(web_search_provider="tavily", tavily_api_key="tvly-test-key")
        request = httpx.Request("POST", "https://api.tavily.com/search")
        client_cm, _client = self._client_context(
            method="post",
            side_effect=httpx.RequestError("network failure", request=request),
        )

        with (
            patch("app.services.tools.citation.sources.web_search.get_settings", return_value=settings),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", return_value=client_cm),
        ):
            candidates, context = source.search_with_context(_reference(), limit=3)

        self.assertEqual(candidates, [])
        self.assertEqual(context["state"], "error")
        self.assertIn("network failure", context["detail"] or "")

    def test_tavily_rate_limit_returns_rate_limited(self) -> None:
        source = WebSearchSource()
        settings = _WebSearchSettings(web_search_provider="tavily", tavily_api_key="tvly-test-key")
        response = _MockResponse(429, {"detail": "rate limited"})
        client_cm, _client = self._client_context(method="post", response=response)

        with (
            patch("app.services.tools.citation.sources.web_search.get_settings", return_value=settings),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", return_value=client_cm),
        ):
            candidates, context = source.search_with_context(_reference(), limit=3)

        self.assertEqual(candidates, [])
        self.assertEqual(context["state"], "rate_limited")
        self.assertEqual(context["detail"], "HTTP 429 (rate limited).")

    def test_tavily_auth_error_returns_http_error(self) -> None:
        source = WebSearchSource()
        settings = _WebSearchSettings(web_search_provider="tavily", tavily_api_key="tvly-test-key")
        response = _MockResponse(401, {"detail": "unauthorized"})
        client_cm, _client = self._client_context(method="post", response=response)

        with (
            patch("app.services.tools.citation.sources.web_search.get_settings", return_value=settings),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", return_value=client_cm),
        ):
            candidates, context = source.search_with_context(_reference(), limit=3)

        self.assertEqual(candidates, [])
        self.assertEqual(context["state"], "http_error")
        self.assertEqual(context["detail"], "HTTP 401 (authentication failed).")

    def test_tavily_forbidden_returns_http_error(self) -> None:
        source = WebSearchSource()
        settings = _WebSearchSettings(web_search_provider="tavily", tavily_api_key="tvly-test-key")
        response = _MockResponse(403, {"detail": "forbidden"})
        client_cm, _client = self._client_context(method="post", response=response)

        with (
            patch("app.services.tools.citation.sources.web_search.get_settings", return_value=settings),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", return_value=client_cm),
        ):
            candidates, context = source.search_with_context(_reference(), limit=3)

        self.assertEqual(candidates, [])
        self.assertEqual(context["state"], "http_error")
        self.assertEqual(context["detail"], "HTTP 403 (access forbidden).")

    def test_tavily_malformed_response_does_not_crash(self) -> None:
        source = WebSearchSource()
        settings = _WebSearchSettings(web_search_provider="tavily", tavily_api_key="tvly-test-key")
        response = _MockResponse(200, ["not-a-dict"])
        client_cm, _client = self._client_context(method="post", response=response)

        with (
            patch("app.services.tools.citation.sources.web_search.get_settings", return_value=settings),
            patch("app.services.tools.citation.sources.web_search.httpx.Client", return_value=client_cm),
        ):
            candidates, context = source.search_with_context(_reference(), limit=3)

        self.assertEqual(candidates, [])
        self.assertEqual(context["state"], "error")
        self.assertIn("Invalid provider payload", context["detail"] or "")


if __name__ == "__main__":
    unittest.main()
