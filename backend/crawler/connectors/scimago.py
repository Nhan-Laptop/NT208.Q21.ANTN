from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from crawler.connectors.base import ConnectorRecord, ConnectorResult, ScholarlyConnector, first_value, parse_int, parse_number, read_tabular_rows, split_list


def parse_scimago_rows(rows: list[dict[str, Any]], source_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        title = first_value(row, "Title", "Source Title", "Journal")
        if not title:
            continue
        issn = first_value(row, "Issn", "ISSN")
        eissn = first_value(row, "EISSN", "eISSN")
        quartile = first_value(row, "SJR Best Quartile", "Quartile", "SJR Quartile")
        sjr = parse_number(first_value(row, "SJR"))
        h_index = parse_int(first_value(row, "H index", "H-index"))
        records.append(
            {
                "title": title,
                "canonical_title": title,
                "venue_type": "journal",
                "issn_print": issn,
                "issn_electronic": eissn,
                "publisher": first_value(row, "Publisher"),
                "country": first_value(row, "Country"),
                "subjects": split_list(first_value(row, "Categories", "Subject Area and Category", "Subject Area")),
                "metric_name": "SJR",
                "metric_value": sjr,
                "sjr_quartile": quartile,
                "h_index": h_index,
                "metric_year": parse_int(first_value(row, "Year")),
                "source_url": source_url,
                "source_name": "SCImago Journal Rank",
                "source_external_id": issn or title,
                "metrics": [
                    {"metric_name": "SJR", "metric_value": sjr},
                    {"metric_name": "SJR quartile", "metric_text": quartile},
                    {"metric_name": "h_index", "metric_value": h_index},
                ],
            }
        )
    return records


class SCImagoConnector(ScholarlyConnector):
    connector_id = "scimago"

    def run(self) -> ConnectorResult:
        candidates = self.source.config.get("download_urls") or [self.source.base_url + "?out=xls"]
        result = ConnectorResult()
        for url in candidates:
            content, snapshot = self.fetch(urljoin(self.source.base_url, url))
            result.snapshots.append(snapshot)
            if snapshot.error_message or not content:
                continue
            rows = read_tabular_rows(content, snapshot.content_type, snapshot.url)
            parsed = parse_scimago_rows(rows, snapshot.url)
            for payload in parsed[: self.limit]:
                result.records.append(ConnectorRecord("venue", payload, snapshot))
            if parsed:
                return result
        result.status = "blocked" if result.snapshots else "failed"
        result.notes.append("No public SCImago CSV/XLS export could be parsed; snapshots record HTTP status.")
        return result
