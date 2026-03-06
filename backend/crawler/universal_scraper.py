"""
Universal Scraper — configuration-driven web scraper for academic CFPs.

Reads target URLs and CSS selectors from ``sources.json`` and returns a
flat list of Call-for-Papers records.  Uses ``cloudscraper`` to bypass
Cloudflare protection.

**Zero Hallucination Policy:** If a publisher blocks the request or returns
no parseable data, that source is silently skipped.  NO fake/mock data is
ever injected.
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import cloudscraper
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_SOURCES_PATH = Path(__file__).parent / "sources.json"


class UniversalScraper:
    """Configuration-driven scraper that reads rules from *sources.json*."""

    def __init__(self, sources_path: str | Path | None = None) -> None:
        path = Path(sources_path) if sources_path else _SOURCES_PATH
        with open(path, "r", encoding="utf-8") as fh:
            self._sources: list[dict[str, Any]] = json.load(fh)
        self._scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False},
        )
        logger.info("Loaded %d source(s) from %s", len(self._sources), path)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def scrape_all(self) -> list[dict[str, Any]]:
        """Scrape every source; return combined list of CFP records."""
        combined: list[dict[str, Any]] = []
        for src in self._sources:
            publisher = src.get("publisher", "Unknown")
            try:
                records = self._scrape_source(src)
                if records:
                    logger.info(
                        "[%s] scraped %d real record(s).",
                        publisher, len(records),
                    )
                    combined.extend(records)
                else:
                    logger.warning(
                        "[%s] returned 0 records (selectors may not match).",
                        publisher,
                    )
            except Exception as exc:
                logger.error(
                    "Failed to scrape %s: %s", publisher, exc,
                )
                # Zero-hallucination: skip this publisher entirely
                continue
        logger.info("Total REAL CFP records: %d", len(combined))
        return combined

    # ------------------------------------------------------------------
    # Internal — single source
    # ------------------------------------------------------------------

    def _scrape_source(self, src: dict[str, Any]) -> list[dict[str, Any]]:
        url = src["url"]
        selectors = src.get("selectors", {})
        base_url = src.get("base_url", "")
        publisher = src.get("publisher", "Unknown")

        resp = self._scraper.get(url, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        container_sel = selectors.get("item_container", "")
        items = soup.select(container_sel) if container_sel else []

        records: list[dict[str, Any]] = []
        for item in items:
            title = self._extract_text(item, selectors.get("title", ""))
            if not title:
                continue
            deadline = self._extract_text(item, selectors.get("deadline", ""))
            scope = self._extract_text(item, selectors.get("scope", ""))
            link = self._extract_link(item, selectors.get("link", ""), base_url)

            records.append({
                "title": title.strip(),
                "deadline": deadline.strip() if deadline else "",
                "scope": scope.strip() if scope else "",
                "url": link or url,
                "publisher": publisher,
                "domains": [],
            })

        # Polite delay between publishers
        time.sleep(random.uniform(1.0, 2.5))
        return records

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(container, selector: str) -> str:
        if not selector:
            return ""
        el = container.select_one(selector)
        return el.get_text(strip=True) if el else ""

    @staticmethod
    def _extract_link(container, selector: str, base_url: str) -> str:
        if not selector:
            return ""
        el = container.select_one(selector)
        if el is None:
            return ""
        href = el.get("href", "")
        if href and not href.startswith("http"):
            href = urljoin(base_url, href)
        return href
