from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

try:
    from dateutil import parser as date_parser
except ImportError:  # pragma: no cover - optional dependency guard
    date_parser = None


class NormalizerService:
    def normalize_text(self, value: str | None) -> str:
        return re.sub(r"\s+", " ", (value or "").strip())

    def normalize_slug(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.normalize_text(value).lower()).strip("-")

    def parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        raw = value.strip()
        for candidate in (raw, raw.replace("Z", "+00:00")):
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed
            except ValueError:
                continue
        if date_parser is not None:
            try:
                parsed = date_parser.parse(raw, fuzzy=True)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed
            except (TypeError, ValueError, OverflowError):
                pass
        return None

    def normalize_list(self, values: list[str] | None) -> list[str]:
        cleaned = []
        seen: set[str] = set()
        for value in values or []:
            item = self.normalize_text(value)
            key = item.lower()
            if item and key not in seen:
                seen.add(key)
                cleaned.append(item)
        return cleaned

    def normalize_venue(self, raw: dict[str, Any]) -> dict[str, Any]:
        title = self.normalize_text(raw.get("title") or raw.get("canonical_title"))
        return {
            "title": title,
            "canonical_title": self.normalize_text(raw.get("canonical_title") or title),
            "venue_type": str(raw.get("venue_type") or "journal").lower(),
            "publisher": self.normalize_text(raw.get("publisher")),
            "issn_print": self.normalize_text(raw.get("issn_print")),
            "issn_electronic": self.normalize_text(raw.get("issn_electronic")),
            "homepage_url": self.normalize_text(raw.get("homepage_url") or raw.get("url")),
            "aims_scope": self.normalize_text(raw.get("aims_scope") or raw.get("scope")),
            "country": self.normalize_text(raw.get("country")),
            "language": self.normalize_text(raw.get("language")),
            "active": bool(raw.get("active", True)),
            "indexed_scopus": bool(raw.get("indexed_scopus", False)),
            "indexed_wos": bool(raw.get("indexed_wos", False)),
            "is_open_access": bool(raw.get("is_open_access", False)),
            "is_hybrid": bool(raw.get("is_hybrid", False)),
            "avg_review_weeks": raw.get("avg_review_weeks"),
            "acceptance_rate": raw.get("acceptance_rate"),
            "apc_usd_min": raw.get("apc_usd_min"),
            "apc_usd_max": raw.get("apc_usd_max"),
            "subjects": self.normalize_list(raw.get("subjects")),
            "aliases": self.normalize_list(raw.get("aliases")),
            "policy": {
                "peer_review_model": self.normalize_text(raw.get("peer_review_model")),
                "open_access_policy": self.normalize_text(raw.get("open_access_policy")),
                "copyright_policy": self.normalize_text(raw.get("copyright_policy")),
                "archiving_policy": self.normalize_text(raw.get("archiving_policy")),
                "apc_usd": raw.get("apc_usd"),
                "turnaround_weeks": raw.get("turnaround_weeks"),
                "notes": self.normalize_text(raw.get("policy_notes")),
            },
            "metric": {
                "metric_year": raw.get("metric_year"),
                "sjr_quartile": self.normalize_text(raw.get("sjr_quartile")).upper() or None,
                "jcr_quartile": self.normalize_text(raw.get("jcr_quartile")).upper() or None,
                "citescore": raw.get("citescore"),
                "impact_factor": raw.get("impact_factor"),
                "h_index": raw.get("h_index"),
                "acceptance_rate": raw.get("metric_acceptance_rate", raw.get("acceptance_rate")),
                "avg_review_weeks": raw.get("metric_avg_review_weeks", raw.get("avg_review_weeks")),
            },
        }

    def normalize_article(self, raw: dict[str, Any]) -> dict[str, Any]:
        title = self.normalize_text(raw.get("title"))
        return {
            "title": title,
            "abstract": self.normalize_text(raw.get("abstract")),
            "doi": self.normalize_text(raw.get("doi")).lower() or None,
            "url": self.normalize_text(raw.get("url")),
            "publication_year": raw.get("publication_year"),
            "publisher": self.normalize_text(raw.get("publisher")),
            "indexed_scopus": bool(raw.get("indexed_scopus", False)),
            "indexed_wos": bool(raw.get("indexed_wos", False)),
            "is_retracted": bool(raw.get("is_retracted", False)),
            "source_name": self.normalize_text(raw.get("source_name")),
            "source_external_id": self.normalize_text(raw.get("source_external_id") or raw.get("doi") or title),
            "published_at": self.parse_datetime(raw.get("published_at")),
            "keywords": self.normalize_list(raw.get("keywords")),
            "authors": raw.get("authors") or [],
        }

    def normalize_cfp(self, raw: dict[str, Any]) -> dict[str, Any]:
        title = self.normalize_text(raw.get("title"))
        return {
            "title": title,
            "description": self.normalize_text(raw.get("description") or raw.get("scope")),
            "topic_tags": self.normalize_list(raw.get("topic_tags") or raw.get("domains")),
            "status": self.normalize_text(raw.get("status")) or "open",
            "abstract_deadline": self.parse_datetime(raw.get("abstract_deadline")),
            "full_paper_deadline": self.parse_datetime(raw.get("full_paper_deadline") or raw.get("deadline")),
            "notification_date": self.parse_datetime(raw.get("notification_date")),
            "event_start_date": self.parse_datetime(raw.get("event_start_date")),
            "event_end_date": self.parse_datetime(raw.get("event_end_date")),
            "mode": self.normalize_text(raw.get("mode")),
            "location": self.normalize_text(raw.get("location")),
            "source_name": self.normalize_text(raw.get("source_name")),
            "source_url": self.normalize_text(raw.get("source_url") or raw.get("url")),
            "publisher": self.normalize_text(raw.get("publisher")),
            "indexed_scopus": bool(raw.get("indexed_scopus", False)),
            "indexed_wos": bool(raw.get("indexed_wos", False)),
        }


normalizer_service = NormalizerService()
