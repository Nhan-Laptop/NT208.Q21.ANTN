from __future__ import annotations

from typing import Any

from app.models.crawl_source import CrawlSource


class AcademicRecordParser:
    def parse(self, source: CrawlSource, payload: Any) -> list[dict[str, Any]]:
        if source.source_type == "bootstrap_json":
            return self._parse_bootstrap(payload)
        if source.source_type == "config_live_cfp":
            return self._parse_live_cfps(payload)
        if source.source_type == "registry_live_source":
            return self._parse_registry_live_source(payload)
        return []

    def _parse_bootstrap(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for venue in payload.get("venues", []):
            records.append({"entity_type": "venue", "payload": venue})
        for article in payload.get("articles", []):
            records.append({"entity_type": "article", "payload": article})
        for cfp in payload.get("cfp_events", []):
            records.append({"entity_type": "cfp", "payload": cfp})
        return records

    def _parse_live_cfps(self, payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"entity_type": "cfp", "payload": row} for row in payload]

    def _parse_registry_live_source(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"entity_type": row["entity_type"], "payload": row["payload"], "snapshot": row.get("snapshot")}
            for row in payload.get("records", [])
            if row.get("entity_type") and isinstance(row.get("payload"), dict)
        ]
