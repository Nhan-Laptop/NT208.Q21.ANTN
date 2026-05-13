from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from crawler.connectors.base import ConnectorRecord, ConnectorResult, ScholarlyConnector, clean_text, extract_links


def parse_springer_journals_html(html: str, source_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for href, text in extract_links(html, source_url):
        marker = href.lower()
        if "/journal/" not in marker and "/journals/" not in marker:
            continue
        title = text or clean_text(href.rstrip("/").rsplit("/", 1)[-1].replace("-", " "))
        if len(title) < 3 or title.lower() in {"journals", "all journals"}:
            continue
        window = html[max(0, html.find(href) - 1000) : html.find(href) + 1200] if href in html else ""
        subjects = []
        for subject in re.findall(r"(?:subject|discipline)[^>]*>\s*([^<]{3,120})", window, flags=re.I):
            subjects.append(clean_text(subject))
        records.append(
            {
                "title": title,
                "canonical_title": title,
                "venue_type": "journal",
                "publisher": "Springer",
                "homepage_url": href,
                "subjects": subjects,
                "source_url": href,
                "source_name": "Springer Link Journals",
                "source_external_id": href,
                "is_open_access": "open access" in window.lower(),
            }
        )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        if record["homepage_url"] not in seen:
            seen.add(record["homepage_url"])
            deduped.append(record)
    return deduped


class SpringerConnector(ScholarlyConnector):
    connector_id = "springer"

    def run(self) -> ConnectorResult:
        result = ConnectorResult()
        letters = self.source.config.get("letters") or list("abcdefghijklmnopqrstuvwxyz")
        per_page_limit = self.source.config.get("pages_per_letter", 1)
        for letter in letters:
            for page in range(1, int(per_page_limit) + 1):
                url = urljoin(self.source.base_url.rstrip("/") + "/", f"{letter}/{page}")
                content, snapshot = self.fetch(url)
                result.snapshots.append(snapshot)
                if snapshot.error_message or not content:
                    continue
                parsed = parse_springer_journals_html(content.decode("utf-8", errors="replace"), snapshot.url)
                for payload in parsed:
                    result.records.append(ConnectorRecord("venue", payload, snapshot))
                    if self.limit and len(result.records) >= self.limit:
                        return result
        if not result.records:
            result.status = "blocked"
            result.notes.append("No Springer journal records were parseable from public A-Z pages.")
        return result
