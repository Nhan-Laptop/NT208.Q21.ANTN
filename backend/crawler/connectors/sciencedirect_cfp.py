from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from crawler.connectors.base import ConnectorRecord, ConnectorResult, ScholarlyConnector, clean_text, extract_links, parse_number


def _deadline_status(value: str | None) -> str:
    if not value:
        return "open"
    try:
        from dateutil import parser as date_parser

        parsed = date_parser.parse(value, fuzzy=True)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return "closed" if parsed < datetime.now(timezone.utc) else "open"
    except Exception:
        return "open"


def parse_sciencedirect_cfp_html(html: str, source_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    links = extract_links(html, source_url)
    for href, text in links:
        marker = f"{href} {text}".lower()
        if "call" not in marker and "special issue" not in marker and "article collection" not in marker:
            continue
        title = text or clean_text(href.rsplit("/", 1)[-1].replace("-", " "))
        if len(title) < 6:
            continue
        window = html[max(0, html.find(href) - 1200) : html.find(href) + 1800] if href in html else html
        deadline = None
        deadline_match = re.search(r"(?:deadline|submission[^<]{0,30})(?:</[^>]+>|\s|:|-)*(.*?)(?:<|$)", window, flags=re.I | re.S)
        if deadline_match:
            deadline = clean_text(deadline_match.group(1))
        journal = None
        journal_match = re.search(r"(?:journal|in)\s*</?[^>]*>\s*([^<]{3,180})", window, flags=re.I)
        if journal_match:
            journal = clean_text(journal_match.group(1))
        records.append(
            {
                "title": title,
                "venue_title": journal,
                "description": clean_text(re.sub(r"<[^>]+>", " ", window))[:2000],
                "full_paper_deadline": deadline,
                "status": _deadline_status(deadline),
                "source_url": href,
                "source_name": "ScienceDirect Calls for Papers",
                "publisher": "Elsevier",
                "source_external_id": href,
                "indexed_scopus": True,
                "impact_factor": parse_number(_search_metric(window, "impact factor")),
                "citescore": parse_number(_search_metric(window, "citescore")),
                "topic_tags": [],
            }
        )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = record["source_url"]
        if key not in seen:
            seen.add(key)
            deduped.append(record)
    return deduped


def _search_metric(text: str, name: str) -> str | None:
    match = re.search(name + r"[^0-9]{0,40}([0-9]+(?:\.[0-9]+)?)", text, flags=re.I)
    return match.group(1) if match else None


class ScienceDirectCFPConnector(ScholarlyConnector):
    connector_id = "sciencedirect_cfp"

    def run(self) -> ConnectorResult:
        result = ConnectorResult()
        content, snapshot = self.fetch(self.source.base_url)
        result.snapshots.append(snapshot)
        if snapshot.error_message or not content:
            result.status = "blocked"
            result.notes.append("ScienceDirect CFP page was not publicly fetchable in this run.")
            return result
        parsed = parse_sciencedirect_cfp_html(content.decode("utf-8", errors="replace"), snapshot.url)
        for payload in parsed[: self.limit]:
            detail_content, detail_snapshot = self.fetch(payload["source_url"])
            result.snapshots.append(detail_snapshot)
            if detail_content and not detail_snapshot.error_message:
                detail_text = clean_text(re.sub(r"<[^>]+>", " ", detail_content.decode("utf-8", errors="replace")))
                if detail_text:
                    payload["description"] = detail_text[:4000]
            result.records.append(ConnectorRecord("cfp", payload, detail_snapshot if detail_content else snapshot))
        return result
