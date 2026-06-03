from __future__ import annotations

import re
from typing import Any

from crawler.connectors.base import ConnectorRecord, ConnectorResult, ScholarlyConnector, clean_text, extract_links, first_value, read_tabular_rows, split_list


def _extract_scopus_subjects(row: dict[str, Any]) -> list[str]:
    direct_subjects = split_list(
        first_value(
            row,
            "ASJC",
            "Subject Area",
            "Top level ASJC",
            "All Science Journal Classification Codes (ASJC)",
            "All Science Journal Classification Codes",
        )
    )
    subjects: list[str] = []
    seen: set[str] = set()

    def _append(value: str | None) -> None:
        cleaned = clean_text(value)
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            subjects.append(cleaned)

    for value in direct_subjects:
        if re.search(r"[A-Za-z]", value):
            _append(value)

    for key, value in row.items():
        label = clean_text(str(key))
        if not label:
            continue
        cell_value = clean_text(str(value))
        if not cell_value:
            continue
        normalized_label = re.sub(r"\s+", " ", label)
        if normalized_label.lower().startswith("top level:"):
            _append(cell_value)
            continue
        match = re.match(r"^\d+\s+(.+)$", normalized_label)
        if match:
            _append(match.group(1))

    return subjects


def parse_scopus_title_list(rows: list[dict[str, Any]], source_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        title = first_value(row, "Source Title", "Title", "Source title")
        if not title:
            continue
        source_type = (first_value(row, "Source Type", "Type") or "journal").lower()
        active_marker = (first_value(row, "Active or Inactive", "Status", "Coverage Status") or "").lower()
        active = "inactive" not in active_marker and "discontinued" not in active_marker
        related_titles = [
            first_value(row, "Title history"),
            first_value(row, "Related Title 1"),
            first_value(row, "Other Related Title 2"),
            first_value(row, "Other Related Title 3"),
            first_value(row, "Other Related Title 4"),
        ]
        records.append(
            {
                "title": title,
                "canonical_title": title,
                "venue_type": "conference" if "conference" in source_type else "journal",
                "issn_print": first_value(row, "ISSN", "Print ISSN"),
                "issn_electronic": first_value(row, "E-ISSN", "eISSN", "Electronic ISSN"),
                "publisher": first_value(row, "Publisher", "Publisher Imprints Grouped to Main Publisher"),
                "active": active,
                "subjects": _extract_scopus_subjects(row),
                "indexed_scopus": True,
                "source_url": source_url,
                "source_name": "Elsevier Scopus Content",
                "source_external_id": first_value(row, "Sourcerecord ID", "Scopus Source ID", "Source ID") or first_value(row, "ISSN") or title,
                "aliases": [value for value in related_titles if value],
                "metrics": [{"metric_name": "Scopus indexed", "metric_text": "true"}],
                "is_open_access": bool(first_value(row, "Open Access Status")),
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
            # Large Scopus title-list workbooks can contain tens of thousands of rows.
            # For bounded crawls, trim rows before subject extraction so targeted imports
            # remain operational instead of paying the full parse cost.
            if self.limit:
                rows = rows[: self.limit]
            parsed = parse_scopus_title_list(rows, snapshot.url)
            for payload in parsed[: self.limit]:
                result.records.append(ConnectorRecord("venue", payload, snapshot))
            if result.records or self.download_only:
                return result
        result.status = "blocked"
        result.notes.append("No public Scopus source-title workbook was discoverable from the content page.")
        return result
