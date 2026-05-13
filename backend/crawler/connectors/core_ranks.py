from __future__ import annotations

import re
from typing import Any

from crawler.connectors.base import ConnectorRecord, ConnectorResult, ScholarlyConnector, clean_text, extract_links, first_value, read_tabular_rows, split_list


def parse_core_rank_rows(rows: list[dict[str, Any]], source_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        name = first_value(row, "Conference Name", "Title", "Name", "Conference")
        acronym = first_value(row, "Acronym", "Abbreviation")
        rank = first_value(row, "Rank", "CORE Rank")
        if not name and not acronym:
            continue
        title = name or acronym
        records.append(
            {
                "title": title,
                "canonical_title": title,
                "venue_type": "conference",
                "aliases": [acronym] if acronym else [],
                "subjects": split_list(first_value(row, "Field", "Discipline", "FoR")),
                "source_url": source_url,
                "source_name": "CORE Conference Ranks",
                "source_external_id": acronym or title,
                "metric_year": None,
                "metrics": [{"metric_name": "CORE rank", "metric_text": rank}],
            }
        )
    return records


def parse_core_rank_html(html: str, source_url: str) -> list[dict[str, Any]]:
    rows: list[dict[str, str]] = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.I | re.S):
        cells = [clean_text(re.sub(r"<[^>]+>", " ", cell)) for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.I | re.S)]
        if len(cells) >= 3 and not any("conference" in cell.lower() and "rank" in cell.lower() for cell in cells):
            rows.append({"Conference Name": cells[0], "Acronym": cells[1], "Rank": cells[2], "Field": cells[3] if len(cells) > 3 else ""})
    return parse_core_rank_rows(rows, source_url)


class CoreRanksConnector(ScholarlyConnector):
    connector_id = "core_ranks"

    def run(self) -> ConnectorResult:
        result = ConnectorResult()
        content, page_snapshot = self.fetch(self.source.base_url)
        result.snapshots.append(page_snapshot)
        if page_snapshot.error_message or not content:
            result.status = "blocked"
            result.notes.append("CORE rank page could not be fetched.")
            return result
        html = content.decode("utf-8", errors="replace")
        candidates = self.source.config.get("download_urls") or []
        for href, text in extract_links(html, page_snapshot.url):
            if any(token in f"{href} {text}".lower() for token in ["csv", "download", "export", "rank"]):
                candidates.append(href)
        for url in candidates:
            content, snapshot = self.fetch(url)
            result.snapshots.append(snapshot)
            if snapshot.error_message or not content:
                continue
            parsed = parse_core_rank_rows(read_tabular_rows(content, snapshot.content_type, snapshot.url), snapshot.url)
            for payload in parsed[: self.limit]:
                result.records.append(ConnectorRecord("venue", payload, snapshot))
            if parsed:
                return result
        parsed = parse_core_rank_html(html, page_snapshot.url)
        for payload in parsed[: self.limit]:
            result.records.append(ConnectorRecord("venue", payload, page_snapshot))
        if not result.records:
            result.status = "blocked"
            result.notes.append("No CORE CSV/export/table records were parseable without interactive access.")
        return result
