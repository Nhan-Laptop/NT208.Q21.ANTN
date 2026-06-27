from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings

from ..models import CandidateWork, ReferenceMetadata
from ..normalize import normalize_doi

logger = logging.getLogger(__name__)

_DISABLED_PROVIDER = "disabled"
_GENERIC_JSON_PROVIDER = "generic_json"
_TAVILY_PROVIDER = "tavily"
_SUPPORTED_PROVIDERS = {_GENERIC_JSON_PROVIDER, _TAVILY_PROVIDER}
_DOI_URL_RE = re.compile(r"https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)
_DOI_TEXT_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]{4,}\b", re.IGNORECASE)
_MAX_PROVIDER_RESULTS = 10
_MAX_QUERY_CHARS = 240
_MAX_TITLE_QUERY_CHARS = 180
_MAX_AUTHOR_QUERY_CHARS = 80
_MAX_AUTHOR_NAME_QUERY_CHARS = 120
_MAX_SNIPPET_CHARS = 900
_MAX_RAW_CONTENT_EXCERPT_CHARS = 1500


@dataclass(frozen=True)
class _ResolvedWebSearchConfig:
    provider: str
    generic_api_key: str | None
    generic_endpoint: str | None
    generic_timeout: float
    tavily_api_key: str | None
    tavily_endpoint: str | None
    tavily_search_depth: str
    tavily_max_results: int
    tavily_include_answer: bool
    tavily_include_raw_content: bool
    tavily_timeout: float


@dataclass(frozen=True)
class _NormalizedSearchHit:
    title: str | None
    url: str | None
    snippet: str | None
    source: str | None = None
    source_domain: str | None = None
    score: float | None = None
    favicon: str | None = None
    raw_content_excerpt: str | None = None


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_plausible_doi(doi: str | None) -> bool:
    if not doi:
        return False
    if len(doi) < 10:
        return False
    return bool(re.fullmatch(r"10\.\d{4,9}/\S{4,}", doi, flags=re.IGNORECASE))


def _normalize_provider(value: Any) -> str | None:
    text = _safe_text(value)
    return text.lower() if text else None


def _truncate_text(value: Any, max_chars: int) -> str | None:
    text = _safe_text(value)
    if not text:
        return None
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    truncated = normalized[:max_chars].rsplit(" ", 1)[0].strip()
    return truncated or normalized[:max_chars].strip()


def _clamp_limit(value: Any, *, default: int = 5) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = default
    return max(1, min(numeric, _MAX_PROVIDER_RESULTS))


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_text(value)
    if text is None:
        return default
    normalized = text.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_doi_candidates(*values: str | None) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        for match in _DOI_URL_RE.findall(value):
            normalized = normalize_doi(match)
            if _is_plausible_doi(normalized) and normalized not in seen:
                seen.add(normalized)
                found.append(normalized)
        for match in _DOI_TEXT_RE.findall(value):
            normalized = normalize_doi(match)
            if _is_plausible_doi(normalized) and normalized not in seen:
                seen.add(normalized)
                found.append(normalized)
    return found


def _derive_source_domain(url: str | None, source_domain: str | None) -> str | None:
    explicit = _safe_text(source_domain)
    if explicit:
        return explicit.lower()
    if not url:
        return None
    try:
        hostname = urlparse(url).hostname
    except ValueError:
        hostname = None
    return hostname.lower() if hostname else None


def _first_author(ref: ReferenceMetadata) -> str | None:
    if not ref.authors:
        return None
    return _safe_text(ref.authors[0])


def _build_queries(ref: ReferenceMetadata) -> list[str]:
    title = _truncate_text(_safe_text(ref.title), _MAX_TITLE_QUERY_CHARS)
    if not title:
        return []
    clean_title = title.replace('"', " ").strip()
    title_query = f"\"{clean_title}\""
    queries: list[str] = []
    first_author = _truncate_text(_first_author(ref), _MAX_AUTHOR_QUERY_CHARS)
    year = str(ref.year) if ref.year is not None else None
    if first_author and year:
        queries.append(f"{title_query} {first_author} {year} DOI")
    if first_author:
        queries.append(f"{title_query} {first_author}")
    queries.append(f"{title_query} DOI")

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = _truncate_text(query, _MAX_QUERY_CHARS)
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def _build_author_publication_queries(author_name: str, source_title: str | None = None) -> list[str]:
    normalized_author = _truncate_text(_safe_text(author_name), _MAX_AUTHOR_NAME_QUERY_CHARS)
    if not normalized_author:
        return []

    clean_author = normalized_author.replace('"', " ").strip()
    author_query = f"\"{clean_author}\""
    clean_source_title = _truncate_text(_safe_text(source_title), _MAX_TITLE_QUERY_CHARS)
    if clean_source_title:
        clean_source_title = clean_source_title.replace('"', " ").strip()

    queries: list[str] = [
        f"{author_query} publications",
        f"{author_query} papers",
        f"{author_query} OpenAlex",
    ]
    if clean_source_title:
        queries.extend(
            [
                f"{author_query} \"{clean_source_title}\"",
                f"{author_query} \"{clean_source_title}\" publications",
            ]
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = _truncate_text(query, _MAX_QUERY_CHARS)
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


class WebSearchSource:
    name = "web_search"

    def lookup_doi(self, doi: str) -> CandidateWork | None:
        return None

    def search(self, ref: ReferenceMetadata, limit: int = 5) -> list[CandidateWork]:
        candidates, _context = self.search_with_context(ref, limit=limit)
        return candidates

    def search_author_publications(
        self,
        author_name: str,
        *,
        source_title: str | None = None,
        limit: int = 5,
    ) -> list[CandidateWork]:
        candidates, _context = self.search_author_publications_with_context(
            author_name,
            source_title=source_title,
            limit=limit,
        )
        return candidates

    def search_with_context(
        self,
        ref: ReferenceMetadata,
        limit: int = 5,
        *,
        provider: str | None = None,
        api_key: str | None = None,
        endpoint: str | None = None,
        timeout: float | None = None,
        tavily_api_key: str | None = None,
        tavily_endpoint: str | None = None,
        tavily_search_depth: str | None = None,
        tavily_max_results: int | None = None,
        tavily_include_answer: bool | None = None,
        tavily_include_raw_content: bool | None = None,
        tavily_timeout_seconds: float | None = None,
    ) -> tuple[list[CandidateWork], dict[str, Any]]:
        provider_limit = _clamp_limit(limit, default=5)
        config = self._resolve_config(
            limit=provider_limit,
            provider=provider,
            api_key=api_key,
            endpoint=endpoint,
            timeout=timeout,
            tavily_api_key=tavily_api_key,
            tavily_endpoint=tavily_endpoint,
            tavily_search_depth=tavily_search_depth,
            tavily_max_results=tavily_max_results,
            tavily_include_answer=tavily_include_answer,
            tavily_include_raw_content=tavily_include_raw_content,
            tavily_timeout_seconds=tavily_timeout_seconds,
        )

        base_context = {
            "provider": config.provider,
            "query": None,
            "state": "skipped",
            "detail": None,
        }

        if not ref or not _safe_text(ref.title):
            base_context["detail"] = "Title is required for web search fallback."
            return [], base_context
        if config.provider == _DISABLED_PROVIDER:
            base_context["state"] = "disabled"
            base_context["detail"] = "WEB_SEARCH_PROVIDER is disabled."
            return [], base_context
        if config.provider not in _SUPPORTED_PROVIDERS:
            base_context["state"] = "disabled"
            base_context["detail"] = f"Unsupported web search provider: {config.provider}."
            return [], base_context

        queries = _build_queries(ref)
        if not queries:
            base_context["detail"] = "Could not build a sufficiently specific web search query."
            return [], base_context

        return self._search_queries_with_context(
            queries,
            limit=provider_limit,
            config=config,
            base_context=base_context,
        )

    def search_author_publications_with_context(
        self,
        author_name: str,
        *,
        source_title: str | None = None,
        limit: int = 5,
        provider: str | None = None,
        api_key: str | None = None,
        endpoint: str | None = None,
        timeout: float | None = None,
        tavily_api_key: str | None = None,
        tavily_endpoint: str | None = None,
        tavily_search_depth: str | None = None,
        tavily_max_results: int | None = None,
        tavily_include_answer: bool | None = None,
        tavily_include_raw_content: bool | None = None,
        tavily_timeout_seconds: float | None = None,
    ) -> tuple[list[CandidateWork], dict[str, Any]]:
        provider_limit = _clamp_limit(limit, default=5)
        config = self._resolve_config(
            limit=provider_limit,
            provider=provider,
            api_key=api_key,
            endpoint=endpoint,
            timeout=timeout,
            tavily_api_key=tavily_api_key,
            tavily_endpoint=tavily_endpoint,
            tavily_search_depth=tavily_search_depth,
            tavily_max_results=tavily_max_results,
            tavily_include_answer=tavily_include_answer,
            tavily_include_raw_content=tavily_include_raw_content,
            tavily_timeout_seconds=tavily_timeout_seconds,
        )

        base_context = {
            "provider": config.provider,
            "query": None,
            "state": "skipped",
            "detail": None,
        }

        if not _safe_text(author_name):
            base_context["detail"] = "Author name is required for author-publication web search fallback."
            return [], base_context
        if config.provider == _DISABLED_PROVIDER:
            base_context["state"] = "disabled"
            base_context["detail"] = "WEB_SEARCH_PROVIDER is disabled."
            return [], base_context
        if config.provider not in _SUPPORTED_PROVIDERS:
            base_context["state"] = "disabled"
            base_context["detail"] = f"Unsupported web search provider: {config.provider}."
            return [], base_context

        queries = _build_author_publication_queries(author_name, source_title=source_title)
        if not queries:
            base_context["detail"] = "Could not build a sufficiently specific author web search query."
            return [], base_context

        return self._search_queries_with_context(
            queries,
            limit=provider_limit,
            config=config,
            base_context=base_context,
        )

    def _search_queries_with_context(
        self,
        queries: list[str],
        *,
        limit: int,
        config: _ResolvedWebSearchConfig,
        base_context: dict[str, Any],
    ) -> tuple[list[CandidateWork], dict[str, Any]]:
        if config.provider == _GENERIC_JSON_PROVIDER:
            if not config.generic_endpoint:
                base_context["state"] = "disabled"
                base_context["detail"] = "WEB_SEARCH_ENDPOINT is not configured."
                return [], base_context
            if not config.generic_api_key:
                base_context["state"] = "disabled"
                base_context["detail"] = "WEB_SEARCH_API_KEY is not configured."
                return [], base_context
            return self._search_generic_json(
                queries,
                limit=limit,
                endpoint=config.generic_endpoint,
                api_key=config.generic_api_key,
                timeout=config.generic_timeout,
                base_context=base_context,
            )

        if not config.tavily_api_key:
            base_context["state"] = "disabled"
            base_context["detail"] = "TAVILY_API_KEY is not configured."
            return [], base_context
        if not config.tavily_endpoint:
            base_context["state"] = "disabled"
            base_context["detail"] = "TAVILY_SEARCH_ENDPOINT is not configured."
            return [], base_context
        return self._search_tavily(
            queries,
            limit=limit,
            endpoint=config.tavily_endpoint,
            api_key=config.tavily_api_key,
            search_depth=config.tavily_search_depth,
            max_results=config.tavily_max_results,
            include_answer=config.tavily_include_answer,
            include_raw_content=config.tavily_include_raw_content,
            timeout=config.tavily_timeout,
            base_context=base_context,
        )

    def _resolve_config(
        self,
        *,
        limit: int,
        provider: str | None,
        api_key: str | None,
        endpoint: str | None,
        timeout: float | None,
        tavily_api_key: str | None,
        tavily_endpoint: str | None,
        tavily_search_depth: str | None,
        tavily_max_results: int | None,
        tavily_include_answer: bool | None,
        tavily_include_raw_content: bool | None,
        tavily_timeout_seconds: float | None,
    ) -> _ResolvedWebSearchConfig:
        settings = get_settings()
        generic_timeout = float(
            timeout if timeout is not None else getattr(settings, "external_search_timeout_seconds", 10.0)
        )
        return _ResolvedWebSearchConfig(
            provider=(
                _normalize_provider(provider)
                or _normalize_provider(getattr(settings, "web_search_provider", None))
                or _DISABLED_PROVIDER
            ),
            generic_api_key=_safe_text(api_key) or _safe_text(getattr(settings, "web_search_api_key", None)),
            generic_endpoint=_safe_text(endpoint) or _safe_text(getattr(settings, "web_search_endpoint", None)),
            generic_timeout=generic_timeout,
            tavily_api_key=_safe_text(tavily_api_key) or _safe_text(getattr(settings, "tavily_api_key", None)),
            tavily_endpoint=_safe_text(tavily_endpoint)
            or _safe_text(getattr(settings, "tavily_search_endpoint", None)),
            tavily_search_depth=(
                _safe_text(tavily_search_depth)
                or _safe_text(getattr(settings, "tavily_search_depth", None))
                or "basic"
            ).lower(),
            tavily_max_results=_clamp_limit(
                tavily_max_results
                if tavily_max_results is not None
                else getattr(settings, "tavily_max_results", limit),
                default=limit,
            ),
            tavily_include_answer=_coerce_bool(
                tavily_include_answer
                if tavily_include_answer is not None
                else getattr(settings, "tavily_include_answer", False)
            ),
            tavily_include_raw_content=_coerce_bool(
                tavily_include_raw_content
                if tavily_include_raw_content is not None
                else getattr(settings, "tavily_include_raw_content", False)
            ),
            tavily_timeout=float(
                tavily_timeout_seconds
                if tavily_timeout_seconds is not None
                else getattr(settings, "tavily_timeout_seconds", generic_timeout)
            ),
        )

    def _search_generic_json(
        self,
        queries: list[str],
        *,
        limit: int,
        endpoint: str,
        api_key: str,
        timeout: float,
        base_context: dict[str, Any],
    ) -> tuple[list[CandidateWork], dict[str, Any]]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "AIRA/1.0 (mailto:aira@research.local)",
        }
        last_no_match_detail = "No usable web results returned."
        for query in queries:
            base_context["query"] = query
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.get(
                        endpoint,
                        params={"q": query, "num": _clamp_limit(limit, default=5)},
                        headers=headers,
                    )
                if response.status_code != 200:
                    logger.warning("Generic web search provider returned status code %s", response.status_code)
                    state, detail = self._http_status_diagnostic(response.status_code)
                    return [], {
                        **base_context,
                        "state": state,
                        "detail": detail,
                    }
                payload = response.json()
            except httpx.TimeoutException:
                logger.warning("Generic web search provider timed out for citation fallback query.")
                return [], {
                    **base_context,
                    "state": "timeout",
                    "detail": "Request timed out.",
                }
            except httpx.RequestError as exc:
                logger.warning("Generic web search provider request failed: %s", exc)
                return [], {
                    **base_context,
                    "state": "error",
                    "detail": str(exc),
                }
            except (TypeError, ValueError) as exc:
                logger.warning("Generic web search provider returned an invalid payload: %s", exc)
                return [], {
                    **base_context,
                    "state": "error",
                    "detail": f"Invalid provider payload: {exc}",
                }

            results = self._extract_results_list(
                payload,
                provider_label="Generic web search provider",
                base_context=base_context,
            )
            if isinstance(results, dict):
                return [], results
            if not results:
                last_no_match_detail = "No web results returned for the fallback query."
                continue

            hits = self._normalize_generic_json_hits(
                results,
                limit=limit,
            )
            candidates = self._candidates_from_hits(
                hits,
                provider=_GENERIC_JSON_PROVIDER,
                query=query,
            )
            if candidates:
                return candidates, {
                    **base_context,
                    "state": "matched",
                    "detail": None,
                }
            last_no_match_detail = "Web results did not contain usable citation evidence."

        return [], {
            **base_context,
            "state": "no_match",
            "detail": last_no_match_detail,
        }

    def _search_tavily(
        self,
        queries: list[str],
        *,
        limit: int,
        endpoint: str,
        api_key: str,
        search_depth: str,
        max_results: int,
        include_answer: bool,
        include_raw_content: bool,
        timeout: float,
        base_context: dict[str, Any],
    ) -> tuple[list[CandidateWork], dict[str, Any]]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AIRA/1.0 (mailto:aira@research.local)",
        }
        effective_limit = min(_clamp_limit(limit, default=5), _clamp_limit(max_results, default=5))
        last_no_match_detail = "No usable Tavily search results returned."
        for query in queries:
            base_context["query"] = query
            payload = {
                "query": query,
                "search_depth": search_depth or "basic",
                "max_results": effective_limit,
                "include_answer": include_answer,
                "include_raw_content": include_raw_content,
            }
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(endpoint, json=payload, headers=headers)
                if response.status_code != 200:
                    logger.warning("Tavily search returned status code %s", response.status_code)
                    state, detail = self._http_status_diagnostic(response.status_code)
                    return [], {
                        **base_context,
                        "state": state,
                        "detail": detail,
                    }
                data = response.json()
            except httpx.TimeoutException:
                logger.warning("Tavily search timed out for citation fallback query.")
                return [], {
                    **base_context,
                    "state": "timeout",
                    "detail": "Request timed out.",
                }
            except httpx.RequestError as exc:
                logger.warning("Tavily search request failed: %s", exc)
                return [], {
                    **base_context,
                    "state": "error",
                    "detail": str(exc),
                }
            except (TypeError, ValueError) as exc:
                logger.warning("Tavily search returned an invalid payload: %s", exc)
                return [], {
                    **base_context,
                    "state": "error",
                    "detail": f"Invalid provider payload: {exc}",
                }

            if not isinstance(data, dict):
                logger.warning("Tavily search returned a non-object payload.")
                return [], {
                    **base_context,
                    "state": "error",
                    "detail": "Invalid provider payload: results envelope must be an object.",
                }

            results = self._extract_results_list(
                data,
                provider_label="Tavily search",
                base_context=base_context,
            )
            if isinstance(results, dict):
                return [], results
            if not results:
                last_no_match_detail = "No Tavily web results returned for the fallback query."
                continue

            hits = self._normalize_tavily_hits(
                results,
                include_raw_content=include_raw_content,
                limit=effective_limit,
            )
            candidates = self._candidates_from_hits(
                hits,
                provider=_TAVILY_PROVIDER,
                query=query,
            )
            if candidates:
                return candidates, {
                    **base_context,
                    "state": "matched",
                    "detail": None,
                }
            last_no_match_detail = "Tavily web results did not contain usable citation evidence."

        return [], {
            **base_context,
            "state": "no_match",
            "detail": last_no_match_detail,
        }

    @staticmethod
    def _http_status_diagnostic(status_code: int) -> tuple[str, str]:
        if status_code == 401:
            return "http_error", "HTTP 401 (authentication failed)."
        if status_code == 403:
            return "http_error", "HTTP 403 (access forbidden)."
        if status_code == 429:
            return "rate_limited", "HTTP 429 (rate limited)."
        return "http_error", f"HTTP {status_code}"

    def _extract_results_list(
        self,
        payload: Any,
        *,
        provider_label: str,
        base_context: dict[str, Any],
    ) -> list[Any] | dict[str, Any]:
        if not isinstance(payload, dict):
            logger.warning("%s returned a non-object payload.", provider_label)
            return {
                **base_context,
                "state": "error",
                "detail": "Invalid provider payload: results envelope must be an object.",
            }
        results = payload.get("results", [])
        if results is None:
            return []
        if not isinstance(results, list):
            logger.warning("%s returned a non-list results payload.", provider_label)
            return {
                **base_context,
                "state": "error",
                "detail": "Invalid provider payload: results must be a list.",
            }
        return results

    def _normalize_generic_json_hits(
        self,
        results: list[Any],
        *,
        limit: int,
    ) -> list[_NormalizedSearchHit]:
        hits: list[_NormalizedSearchHit] = []
        for item in results[: _clamp_limit(limit, default=5)]:
            if not isinstance(item, dict):
                continue
            hits.append(
                _NormalizedSearchHit(
                    title=_truncate_text(item.get("title"), _MAX_TITLE_QUERY_CHARS),
                    url=_safe_text(item.get("url")),
                    snippet=_truncate_text(item.get("snippet") or item.get("content"), _MAX_SNIPPET_CHARS),
                    source=_safe_text(item.get("source")),
                    source_domain=_safe_text(item.get("source_domain")),
                    score=_safe_float(item.get("score")),
                )
            )
        return hits

    def _normalize_tavily_hits(
        self,
        results: list[Any],
        *,
        include_raw_content: bool,
        limit: int,
    ) -> list[_NormalizedSearchHit]:
        hits: list[_NormalizedSearchHit] = []
        for item in results[: _clamp_limit(limit, default=5)]:
            if not isinstance(item, dict):
                continue
            hits.append(
                _NormalizedSearchHit(
                    title=_truncate_text(item.get("title"), _MAX_TITLE_QUERY_CHARS),
                    url=_safe_text(item.get("url")),
                    snippet=_truncate_text(item.get("content"), _MAX_SNIPPET_CHARS),
                    source=_safe_text(item.get("source")),
                    source_domain=_safe_text(item.get("source_domain")),
                    score=_safe_float(item.get("score")),
                    favicon=_safe_text(item.get("favicon")),
                    raw_content_excerpt=_truncate_text(
                        item.get("raw_content") if include_raw_content else None,
                        _MAX_RAW_CONTENT_EXCERPT_CHARS,
                    ),
                )
            )
        return hits

    def _candidates_from_hits(
        self,
        hits: list[_NormalizedSearchHit],
        *,
        provider: str,
        query: str,
    ) -> list[CandidateWork]:
        candidates: list[CandidateWork] = []
        for hit in hits:
            candidate = self._candidate_from_hit(hit, provider=provider, query=query)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _candidate_from_hit(
        self,
        hit: _NormalizedSearchHit,
        *,
        provider: str,
        query: str,
    ) -> CandidateWork | None:
        if not any([hit.title, hit.url, hit.snippet]):
            return None

        doi_candidates = _extract_doi_candidates(hit.url, hit.snippet, hit.title)
        normalized_source_domain = _derive_source_domain(hit.url, hit.source_domain)
        raw: dict[str, Any] = {
            "snippet": hit.snippet,
            "content": hit.snippet,
            "source_domain": normalized_source_domain,
            "web_search_provider": provider,
            "web_search_query": query,
        }
        if hit.source:
            raw["source"] = hit.source
        if hit.favicon:
            raw["favicon"] = hit.favicon
        if hit.score is not None:
            raw["score"] = hit.score
        if doi_candidates:
            raw["doi_candidates"] = doi_candidates
        if len(doi_candidates) > 1:
            raw["doi_ambiguity"] = "multiple_dois_found_in_result"
        if hit.raw_content_excerpt:
            raw["raw_content_excerpt"] = hit.raw_content_excerpt

        return CandidateWork(
            source=self.name,
            title=hit.title,
            doi=doi_candidates[0] if len(doi_candidates) == 1 else None,
            url=hit.url,
            raw=raw,
            evidence_urls=[hit.url] if hit.url else [],
            source_domain=normalized_source_domain,
        )

    def _candidate_from_result(
        self,
        *,
        title: Any,
        url: Any,
        snippet: Any,
        provider: str,
        query: str,
        source_domain: Any = None,
        score: Any = None,
        source_name: Any = None,
        favicon: Any = None,
        raw_content: Any = None,
    ) -> CandidateWork | None:
        return self._candidate_from_hit(
            _NormalizedSearchHit(
                title=_truncate_text(title, _MAX_TITLE_QUERY_CHARS),
                url=_safe_text(url),
                snippet=_truncate_text(snippet, _MAX_SNIPPET_CHARS),
                source=_safe_text(source_name),
                source_domain=_safe_text(source_domain),
                score=_safe_float(score),
                favicon=_safe_text(favicon),
                raw_content_excerpt=_truncate_text(raw_content, _MAX_RAW_CONTENT_EXCERPT_CHARS),
            ),
            provider=provider,
            query=query,
        )
