from __future__ import annotations

import re
from typing import Any

from crawler.connectors.base import ConnectorRecord, ConnectorResult, ScholarlyConnector, clean_text, extract_links, first_value, read_tabular_rows, split_list


def parse_scopus_title_list(rows: list[dict[str, Any]], source_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        title = first_value(row, "Source Title", "Title", "Source title")
        if not title:
            continue
        source_type = (first_value(row, "Source Type", "Type") or "journal").lower()
        records.append(
            {
                "title": title,
                "canonical_title": title,
                "venue_type": "conference" if "conference" in source_type else "journal",
                "issn_print": first_value(row, "ISSN", "Print ISSN"),
                "issn_electronic": first_value(row, "E-ISSN", "eISSN", "Electronic ISSN"),
                "publisher": first_value(row, "Publisher"),
                "active": "discontinued" not in (first_value(row, "Status", "Coverage Status") or "").lower(),
                "subjects": split_list(first_value(row, "ASJC", "Subject Area", "Top level ASJC", "All Science Journal Classification Codes (ASJC)", "All Science Journal Classification Codes")),
                "indexed_scopus": True,
                "source_url": source_url,
                "source_name": "Elsevier Scopus Content",
                "source_external_id": first_value(row, "Scopus Source ID", "Source ID") or first_value(row, "ISSN") or title,
                "aliases": [first_value(row, "Title history")] if first_value(row, "Title history") else [],
                "metrics": [{"metric_name": "Scopus indexed", "metric_text": "true"}],
            }
        )
    return records


class ScopusConnector(ScholarlyConnector):
    connector_id = "scopus"

    def run(self) -> ConnectorResult:
        result = ConnectorResult()
        content, page_snapshot = self.fetch(self.source.base_url)
        result.snapshots.append(page_snapshot)
        if page_snapshot.error_message or not content:
            result.status = "blocked"
            result.notes.append("Scopus content page could not be fetched or is access-limited.")
            return result
        html = content.decode("utf-8", errors="replace")
        links = extract_links(html, page_snapshot.url)
        configured = self.source.config.get("download_urls") or []
        candidates = list(configured)
        for href, text in links:
            marker = f"{href} {text}".lower()
            if re.search(r"(source|book).*title.*\.(xlsx|xls|csv)|\.(xlsx|csv)", marker):
                candidates.append(href)
        seen: set[str] = set()
        for url in candidates:
            if url in seen:
                continue
            seen.add(url)
            content, snapshot = self.fetch(url)
            result.snapshots.append(snapshot)
            if snapshot.error_message or not content:
                continue
            rows = read_tabular_rows(content, snapshot.content_type, snapshot.url)
            parsed = parse_scopus_title_list(rows, snapshot.url)
            for payload in parsed[: self.limit]:
                result.records.append(ConnectorRecord("venue", payload, snapshot))
            if result.records or self.download_only:
                return result
        result.status = "blocked"
        result.notes.append("No public Scopus source-title workbook was discoverable from the content page.")
        return result
