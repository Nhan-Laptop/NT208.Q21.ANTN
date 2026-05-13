"""
Universal Scraper — configuration-driven live scraper for academic CFPs.

Reads target URLs and CSS selectors from ``sources.json`` and returns a
flat list of Call-for-Papers records. Uses DrissionPage's CDP-backed
Chromium automation so dynamic CFP pages can be rendered before
extraction.

**Zero Hallucination Policy:** If a publisher blocks the browser session,
fails to render, or returns no parseable data, that source is skipped.
NO fake/mock data is ever injected.
"""

from __future__ import annotations

import json
import logging
import html
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from app.core.config import settings
from DrissionPage import ChromiumOptions, ChromiumPage

logger = logging.getLogger(__name__)

_SOURCES_PATH = Path(__file__).parent / "sources.json"
_DEFAULT_WAIT_SECONDS = 3.0
_BLOCKED_MARKERS = (
    "access denied",
    "request blocked",
    "you don't have permission",
    "cf-ray",
    "cloudflare",
    "cloudfront",
    "captcha",
    "verify you are human",
)
_CFP_KEYWORDS = (
    "call for papers",
    "call for submissions",
    "special issue",
    "submission deadline",
    "submissions due",
)
_LINK_HINTS = (
    "call-for-papers",
    "call_for_papers",
    "special-issue",
    "special_issue",
    "conference",
)
_DEADLINE_PATTERNS = (
    re.compile(
        r"(submission deadline|submissions due|deadline)\s*[:\-]?\s*(.{4,80}?)"
        r"(?=(publication date|learn more|why participate|topics|submit your|$))",
        re.IGNORECASE | re.DOTALL,
    ),
)

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _resolve_backend_path(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = _BACKEND_ROOT / path
    return str(path.resolve())


class UniversalScraper:
    """Configuration-driven scraper that reads rules from *sources.json*."""

    def __init__(
        self,
        sources_path: str | Path | None = None,
        *,
        headless: bool = True,
        wait_seconds: float = _DEFAULT_WAIT_SECONDS,
    ) -> None:
        path = Path(sources_path) if sources_path else _SOURCES_PATH
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            raw = raw.get("sources", raw)
        if not isinstance(raw, list):
            raw = []
        self._sources: list[dict[str, Any]] = raw
        self._default_wait = wait_seconds

        co = ChromiumOptions()
        browser_path = _resolve_backend_path(settings.academic_browser_path)
        if browser_path:
            co.set_browser_path(browser_path)
        library_path = _resolve_backend_path(settings.academic_browser_library_path)
        if library_path:
            existing = os.environ.get("LD_LIBRARY_PATH")
            os.environ["LD_LIBRARY_PATH"] = f"{library_path}:{existing}" if existing else library_path
        if headless:
            co.headless()
            co.set_argument("--headless=new")
        co.set_local_port(9223)
        co.set_user_data_path(str((_BACKEND_ROOT / ".cache" / "drissionpage-profile").resolve()))
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-dev-shm-usage")
        co.set_argument("--disable-gpu")
        co.set_argument("--disable-background-networking")
        co.set_argument("--disable-sync")
        co.set_argument("--disable-component-update")
        co.set_argument("--disable-features", "HttpsUpgrades,HttpsFirstBalancedModeAutoEnable")
        self.page = ChromiumPage(co)

        logger.info(
            "Loaded %d source(s) from %s using DrissionPage.",
            len(self._sources),
            path,
        )

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def scrape_all(self) -> list[dict[str, Any]]:
        """Scrape every source; return combined list of CFP records."""
        combined: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str]] = set()

        for src in self._sources:
            publisher = src.get("publisher", "Unknown")
            try:
                records = self._scrape_source(src)
                if records:
                    logger.info(
                        "[%s] DrissionPage scraped %d real record(s).",
                        publisher, len(records),
                    )
                    for record in records:
                        record_key = (record.get("url", ""), record.get("title", ""))
                        if record_key in seen_keys:
                            continue
                        seen_keys.add(record_key)
                        combined.append(record)
                else:
                    logger.warning(
                        "[%s] returned 0 records after live DOM extraction.",
                        publisher,
                    )
            except Exception as exc:
                logger.error(
                    "Failed to scrape %s with DrissionPage: %s", publisher, exc,
                )
                # Zero-hallucination: skip this publisher entirely
                continue
        logger.info(
            "Total REAL CFP records scraped with DrissionPage: %d",
            len(combined),
        )
        return combined

    def close(self) -> None:
        """Close the underlying browser session."""
        for method_name in ("quit", "close"):
            method = getattr(self.page, method_name, None)
            if callable(method):
                try:
                    method()
                    return
                except Exception:
                    continue

    # ------------------------------------------------------------------
    # Internal — single source
    # ------------------------------------------------------------------

    def _scrape_source(self, src: dict[str, Any]) -> list[dict[str, Any]]:
        if src.get("parser") == "wikicfp_recent":
            return self._scrape_wikicfp_recent(src)

        url = src["url"]
        selectors = src.get("selectors", {})
        base_url = src.get("base_url", "")
        publisher = src.get("publisher", "Unknown")
        wait_seconds = float(src.get("wait_seconds", self._default_wait))

        logger.info("[%s] Loading %s via DrissionPage.", publisher, url)
        self.page.get(url)
        self.page.wait(wait_seconds)

        body_text = self._safe_text(self.page.ele("css:body"))
        if self._looks_blocked(body_text):
            logger.warning(
                "[%s] page appears blocked after render; skipping without fake data.",
                publisher,
            )
            return []

        items = self._find_items(selectors.get("item_container"))
        if not items:
            logger.warning(
                "[%s] no items matched selector(s): %s",
                publisher,
                selectors.get("item_container", ""),
            )
            return []

        records: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str]] = set()
        for item in items:
            item_text = self._safe_text(item)
            title = self._extract_text(item, selectors.get("title", ""))
            if not title:
                title = self._extract_text(item, "a[href], h1, h2, h3, h4")
            if not title:
                continue

            deadline = self._extract_text(item, selectors.get("deadline", ""))
            if not deadline:
                deadline = self._extract_deadline(item_text)

            scope = self._extract_text(item, selectors.get("scope", ""))
            if not scope:
                scope = self._derive_scope(item_text, title, deadline)

            link = self._extract_link(item, selectors.get("link", ""), base_url)
            if not link:
                link = self._extract_link(item, "a[href]", base_url)

            if not self._is_probable_cfp(title, scope, link, deadline, item_text):
                continue

            record = {
                "title": title,
                "deadline": deadline,
                "scope": scope,
                "url": link or url,
                "publisher": publisher,
                "domains": [],
            }
            record_key = (record["url"], record["title"])
            if record_key in seen_keys:
                continue
            seen_keys.add(record_key)
            records.append(record)

        return records

    def _scrape_wikicfp_recent(self, src: dict[str, Any]) -> list[dict[str, Any]]:
        url = src["url"]
        publisher = src.get("publisher", "WikiCFP")
        base_url = src.get("base_url", "http://www.wikicfp.com")
        wait_seconds = float(src.get("wait_seconds", self._default_wait))

        logger.info("[%s] Loading %s via DrissionPage.", publisher, url)
        self.page.get(url)
        self.page.wait(wait_seconds)

        body_text = self._safe_text(self.page.ele("css:body"))
        if self._looks_blocked(body_text):
            logger.warning("[%s] page appears blocked after render; skipping without fake data.", publisher)
            return []

        html_text = getattr(self.page, "html", "") or ""
        row_pattern = re.compile(
            r"<tr[^>]*>\s*"
            r"<td[^>]*rowspan=[\"']?2[\"']?[^>]*>\s*<a\s+href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<title>.*?)</a>.*?</td>\s*"
            r"<td[^>]*colspan=[\"']?3[\"']?[^>]*>(?P<description>.*?)</td>.*?</tr>\s*"
            r"<tr[^>]*>\s*"
            r"<td[^>]*>(?P<event_dates>.*?)</td>\s*"
            r"<td[^>]*>(?P<location>.*?)</td>\s*"
            r"<td[^>]*>(?P<deadline>.*?)</td>",
            re.IGNORECASE | re.DOTALL,
        )
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for match in row_pattern.finditer(html_text):
            title = self._html_to_text(match.group("title"))
            href = html.unescape(match.group("href"))
            link = self._resolve_url(base_url, href)
            if not title or link in seen:
                continue
            seen.add(link)
            description = self._html_to_text(match.group("description"))
            deadline = self._html_to_text(match.group("deadline"))
            if deadline.upper() == "TBD":
                deadline = ""
            records.append(
                {
                    "title": title,
                    "deadline": deadline,
                    "scope": description,
                    "url": link,
                    "publisher": publisher,
                    "location": self._html_to_text(match.group("location")),
                    "event_dates": self._html_to_text(match.group("event_dates")),
                    "domains": ["computer science", "call for papers"],
                    "source_external_id": href,
                    "source_name": publisher,
                }
            )
        return records[: int(src.get("max_records", 10))]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_items(self, selector_value: Any) -> list[Any]:
        for selector in self._selector_candidates(selector_value):
            try:
                items = self.page.eles(f"css:{selector}") or []
            except Exception:
                continue
            if items:
                return items
        return []

    def _extract_text(self, container: Any, selector_value: Any) -> str:
        for selector in self._selector_candidates(selector_value):
            try:
                element = container.ele(f"css:{selector}")
            except Exception:
                continue
            text = self._safe_text(element)
            if text:
                return text
        return ""

    def _extract_link(self, container: Any, selector_value: Any, base_url: str) -> str:
        for selector in self._selector_candidates(selector_value):
            try:
                element = container.ele(f"css:{selector}")
            except Exception:
                continue
            link = self._safe_link(element)
            if link:
                return self._resolve_url(base_url, link)
        return ""

    @staticmethod
    def _selector_candidates(selector_value: Any) -> list[str]:
        if isinstance(selector_value, str):
            selector = selector_value.strip()
            return [selector] if selector else []
        if isinstance(selector_value, list):
            return [
                str(selector).strip()
                for selector in selector_value
                if str(selector).strip()
            ]
        return []

    @staticmethod
    def _clean_text(text: str) -> str:
        return " ".join(text.split()).strip()

    def _html_to_text(self, raw_html: str) -> str:
        without_tags = re.sub(r"<[^>]+>", " ", raw_html or "")
        return self._clean_text(html.unescape(without_tags))

    def _safe_text(self, element: Any) -> str:
        if element is None:
            return ""
        for attr in ("text", "raw_text"):
            try:
                value = getattr(element, attr)
            except Exception:
                continue
            if isinstance(value, str) and value.strip():
                return self._clean_text(value)
        return ""

    @staticmethod
    def _safe_link(element: Any) -> str:
        if element is None:
            return ""
        for getter in (
            lambda ele: ele.link,
            lambda ele: ele.attr("href"),
        ):
            try:
                value = getter(element)
            except Exception:
                continue
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _resolve_url(base_url: str, href: str) -> str:
        if not href:
            return ""
        if href.startswith(("http://", "https://")):
            return href
        if href.startswith(("javascript:", "mailto:")):
            return ""
        return urljoin(base_url, href)

    @staticmethod
    def _looks_blocked(text: str) -> bool:
        lowered = text.lower()
        return any(marker in lowered for marker in _BLOCKED_MARKERS)

    def _extract_deadline(self, text: str) -> str:
        if not text:
            return ""
        for pattern in _DEADLINE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            deadline = self._clean_text(match.group(2))
            if deadline:
                return deadline
        return ""

    def _derive_scope(self, text: str, title: str, deadline: str) -> str:
        if not text:
            return ""
        scope = text
        for fragment in (title, deadline):
            if fragment:
                scope = scope.replace(fragment, "", 1)
        for marker in ("Learn More", "Submit Your Content", "Why Participate"):
            if marker in scope:
                scope = scope.split(marker, 1)[0]
        return self._clean_text(scope)[:1200]

    @staticmethod
    def _is_probable_cfp(
        title: str,
        scope: str,
        link: str,
        deadline: str,
        raw_text: str,
    ) -> bool:
        combined = " ".join([title, scope, raw_text]).lower()
        link_value = link.lower()
        if deadline:
            return True
        if any(hint in link_value for hint in _LINK_HINTS):
            return True
        return any(keyword in combined for keyword in _CFP_KEYWORDS)
