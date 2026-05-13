from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings


@dataclass(frozen=True)
class SourceConfig:
    id: str
    name: str
    base_url: str
    source_type: str
    access_mode: str
    crawl_strategy: str
    allowed_domains: list[str]
    rate_limit: float
    enabled: bool
    priority: int
    parser: str
    expected_entities: list[str]
    notes: str | None = None
    config: dict[str, Any] | None = None


class SourceRegistry:
    REQUIRED_KEYS = {
        "id",
        "name",
        "base_url",
        "source_type",
        "access_mode",
        "crawl_strategy",
        "allowed_domains",
        "rate_limit",
        "enabled",
        "priority",
        "parser",
        "expected_entities",
    }

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self.default_path()

    @staticmethod
    def default_path() -> Path:
        backend_root = Path(__file__).resolve().parents[2]
        path = Path(settings.academic_live_sources_path)
        return path if path.is_absolute() else backend_root / path

    def load(self) -> list[SourceConfig]:
        with open(self.path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        items = payload.get("sources", payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("crawler source registry must be a list or {'sources': list}")
        configs: list[SourceConfig] = []
        for item in items:
            missing = self.REQUIRED_KEYS - set(item)
            if missing:
                raise ValueError(f"source {item.get('id') or item.get('name')} missing keys: {sorted(missing)}")
            configs.append(
                SourceConfig(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    base_url=str(item["base_url"]),
                    source_type=str(item["source_type"]),
                    access_mode=str(item["access_mode"]),
                    crawl_strategy=str(item["crawl_strategy"]),
                    allowed_domains=[str(domain) for domain in item.get("allowed_domains") or []],
                    rate_limit=float(item.get("rate_limit") or settings.crawler_rate_limit_seconds),
                    enabled=bool(item.get("enabled", True)),
                    priority=int(item.get("priority") or 100),
                    parser=str(item["parser"]),
                    expected_entities=[str(entity) for entity in item.get("expected_entities") or []],
                    notes=item.get("notes"),
                    config=item.get("config") or {},
                )
            )
        return sorted(configs, key=lambda source: (source.priority, source.id))

    def get(self, source_id: str) -> SourceConfig:
        for source in self.load():
            if source.id == source_id:
                return source
        raise KeyError(source_id)


source_registry = SourceRegistry()
