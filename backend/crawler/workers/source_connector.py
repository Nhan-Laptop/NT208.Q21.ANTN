from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.crawl_source import CrawlSource
from crawler.connectors.registry import build_connector
from crawler.connectors.source_registry import source_registry


class BootstrapSeedConnector:
    def fetch(self, source: CrawlSource) -> dict[str, Any]:
        backend_root = Path(__file__).resolve().parents[2]
        seed_path = (backend_root / settings.academic_seed_path).resolve()
        with open(seed_path, "r", encoding="utf-8") as handle:
            return json.load(handle)


class ConfiguredCFPConnector:
    def fetch(self, source: CrawlSource) -> list[dict[str, Any]]:
        from crawler.universal_scraper import UniversalScraper

        backend_root = Path(__file__).resolve().parents[2]
        sources_path = Path(source.base_url or settings.academic_live_sources_path)
        if not sources_path.is_absolute():
            sources_path = backend_root / sources_path
        scraper = UniversalScraper(sources_path=sources_path)
        try:
            return scraper.scrape_all()
        finally:
            scraper.close()


class RegistrySourceConnector:
    def __init__(self, *, limit: int | None = None, download_only: bool = False) -> None:
        self.limit = limit
        self.download_only = download_only

    def fetch(self, source: CrawlSource, *, crawl_run_id: str | None = None) -> dict[str, Any]:
        source_id = (source.config_json or {}).get("source_id") or source.slug
        config = source_registry.get(source_id)
        connector = build_connector(config, limit=self.limit, download_only=self.download_only, crawl_run_id=crawl_run_id)
        result = connector.run()
        return {
            "status": result.status,
            "notes": result.notes,
            "records": [
                {"entity_type": record.entity_type, "payload": record.payload, "snapshot": record.snapshot}
                for record in result.records
            ],
            "snapshots": result.snapshots,
        }
