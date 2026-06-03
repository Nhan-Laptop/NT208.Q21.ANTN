from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree as ET

import httpx

from app.core.config import settings
from crawler.connectors.source_registry import SourceConfig

logger = logging.getLogger(__name__)

PARSER_VERSION = "live-connectors-v1"


@dataclass
class SnapshotInfo:
    source_id: str
    url: str
    fetched_at: str
    status_code: int | None
    content_type: str | None
    content_length: int | None
    content_hash: str | None
    storage_path: str | None = None
    error_message: str | None = None
    parser_version: str = PARSER_VERSION
    crawl_run_id: str | None = None


@dataclass
class ConnectorRecord:
    entity_type: str
    payload: dict[str, Any]
    snapshot: SnapshotInfo | None = None


@dataclass
class ConnectorResult:
    records: list[ConnectorRecord] = field(default_factory=list)
    snapshots: list[SnapshotInfo] = field(default_factory=list)
    status: str = "succeeded"
    notes: list[str] = field(default_factory=list)


class LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            attrs_dict = {key.lower(): value for key, value in attrs}
            self._href = attrs_dict.get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            self.links.append((self._href, clean_text(" ".join(self._text))))
            self._href = None
            self._text = []


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def normalized_title(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


def sha256_bytes(content: bytes | None) -> str | None:
    if not content:
        return None
    return hashlib.sha256(content).hexdigest()


def first_value(row: dict[str, Any], *names: str) -> str | None:
    lowered = {clean_text(key).lower(): value for key, value in row.items()}
    for name in names:
        key = name.lower()
        if key in lowered and clean_text(str(lowered[key])):
            return clean_text(str(lowered[key]))
    for actual_key, value in lowered.items():
        compact = re.sub(r"[^a-z0-9]+", "", actual_key)
        for name in names:
            if re.sub(r"[^a-z0-9]+", "", name.lower()) == compact and clean_text(str(value)):
                return clean_text(str(value))
    return None


def split_list(value: str | None) -> list[str]:
    if not value:
        return []
    parts = re.split(r"\s*(?:;|\||,>\s*|,\s*(?=[A-Z][a-z]))\s*", value)
    return [clean_text(part) for part in parts if clean_text(part)]


def parse_number(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = re.sub(r"[^0-9.,-]+", "", value).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    number = parse_number(value)
    return int(number) if number is not None else None


def read_csv_rows(content: bytes) -> list[dict[str, str]]:
    text = content.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [dict(row) for row in csv.DictReader(io.StringIO(text), dialect=dialect)]


def read_xlsx_rows(content: bytes) -> list[dict[str, str]]:
    """Small XLSX reader for public title-list exports without adding pandas/openpyxl."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            namespace = {"x": shared_root.tag.split("}")[0].lstrip("{")} if shared_root.tag.startswith("{") else {}
            items = shared_root.findall(".//x:si", namespace) if namespace else shared_root.findall(".//si")
            for item in items:
                texts = item.findall(".//x:t", namespace) if namespace else item.findall(".//t")
                shared_strings.append(clean_text("".join(text.text or "" for text in texts)))
        sheet_name = next((name for name in archive.namelist() if name.startswith("xl/worksheets/sheet")), None)
        if not sheet_name:
            return []
        sheet_root = ET.fromstring(archive.read(sheet_name))

    namespace = {"x": sheet_root.tag.split("}")[0].lstrip("{")} if sheet_root.tag.startswith("{") else {}
    row_nodes = sheet_root.findall(".//x:row", namespace) if namespace else sheet_root.findall(".//row")
    rows: list[list[str]] = []
    for row_node in row_nodes:
        row: list[str] = []
        cell_nodes = row_node.findall("x:c", namespace) if namespace else row_node.findall("c")
        for cell in cell_nodes:
            ref = cell.attrib.get("r", "")
            ref_match = re.match(r"([A-Z]+)\d+", ref)
            value_node = cell.find("x:v", namespace) if namespace else cell.find("v")
            inline_text_nodes = cell.findall(".//x:t", namespace) if namespace else cell.findall(".//t")
            value = clean_text("".join(node.text or "" for node in inline_text_nodes)) if inline_text_nodes else clean_text(value_node.text if value_node is not None and value_node.text else "")
            if cell.attrib.get("t") == "s" and value.isdigit():
                index = int(value)
                value = shared_strings[index] if index < len(shared_strings) else ""
            if ref_match:
                column_letters = ref_match.group(1)
                column_index = 0
                for letter in column_letters:
                    column_index = column_index * 26 + (ord(letter) - ord("A") + 1)
                column_index -= 1
            else:
                column_index = len(row)
            if column_index >= len(row):
                row.extend([""] * (column_index - len(row) + 1))
            row[column_index] = value
        if any(row):
            rows.append(row)
    if not rows:
        return []
    headers = [clean_text(header) for header in rows[0]]
    return [dict(zip(headers, row + [""] * (len(headers) - len(row)))) for row in rows[1:]]


def read_tabular_rows(content: bytes, content_type: str | None = None, url: str | None = None) -> list[dict[str, str]]:
    marker = (content_type or url or "").lower()
    if ".xlsx" in marker or "spreadsheet" in marker or content[:2] == b"PK":
        return read_xlsx_rows(content)
    return read_csv_rows(content)


def extract_links(html: str, base_url: str) -> list[tuple[str, str]]:
    parser = LinkExtractor()
    parser.feed(html)
    return [(urljoin(base_url, href), text) for href, text in parser.links if href]


class ScholarlyConnector:
    connector_id = "base"

    def __init__(self, source: SourceConfig, *, limit: int | None = None, download_only: bool = False, crawl_run_id: str | None = None) -> None:
        self.source = source
        self.limit = limit
        self.download_only = download_only
        self.crawl_run_id = crawl_run_id
        self._last_request_at = 0.0

    def run(self) -> ConnectorResult:
        raise NotImplementedError

    def _raw_root(self) -> Path:
        root = Path(settings.crawler_raw_storage_path)
        if not root.is_absolute():
            root = Path(__file__).resolve().parents[2] / root
        return root

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": settings.crawler_user_agent, "Accept": "text/html,application/xhtml+xml,application/xml,text/csv,*/*;q=0.8"}

    def _allowed_by_robots(self, url: str) -> tuple[bool, str | None]:
        if not self.source.allowed_domains:
            return True, None
        parsed = urlparse(url)
        if parsed.hostname and parsed.hostname not in self.source.allowed_domains:
            return False, f"domain_not_allowed:{parsed.hostname}"
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            parser.read()
        except Exception as exc:
            logger.info("robots.txt unavailable for %s: %s", robots_url, exc)
            return True, None
        if not parser.can_fetch(settings.crawler_user_agent, url):
            return False, "blocked_by_robots_txt"
        return True, None

    def fetch(self, url: str) -> tuple[bytes, SnapshotInfo]:
        fetched_at = datetime.now(timezone.utc).isoformat()
        allowed, reason = self._allowed_by_robots(url)
        if not allowed:
            snapshot = SnapshotInfo(
                source_id=self.source.id,
                url=url,
                fetched_at=fetched_at,
                status_code=None,
                content_type=None,
                content_length=None,
                content_hash=None,
                error_message=reason,
                crawl_run_id=self.crawl_run_id,
            )
            return b"", snapshot
        elapsed = time.monotonic() - self._last_request_at
        rate_limit = max(float(self.source.rate_limit or settings.crawler_rate_limit_seconds), 0.0)
        if elapsed < rate_limit:
            time.sleep(rate_limit - elapsed)
        self._last_request_at = time.monotonic()
        try:
            with httpx.Client(timeout=settings.crawler_timeout_seconds, follow_redirects=True, headers=self._headers()) as client:
                response = client.get(url)
            content = response.content or b""
            content_hash = sha256_bytes(content)
            storage_path = self._write_snapshot(url, content, content_hash) if content else None
            error = None
            if response.status_code in {401, 403, 429}:
                error = f"http_{response.status_code}"
            snapshot = SnapshotInfo(
                source_id=self.source.id,
                url=str(response.url),
                fetched_at=fetched_at,
                status_code=response.status_code,
                content_type=response.headers.get("content-type"),
                content_length=len(content),
                content_hash=content_hash,
                storage_path=storage_path,
                error_message=error,
                crawl_run_id=self.crawl_run_id,
            )
            return content, snapshot
        except Exception as exc:
            return b"", SnapshotInfo(
                source_id=self.source.id,
                url=url,
                fetched_at=fetched_at,
                status_code=None,
                content_type=None,
                content_length=None,
                content_hash=None,
                error_message=str(exc),
                crawl_run_id=self.crawl_run_id,
            )

    def _write_snapshot(self, url: str, content: bytes, content_hash: str | None) -> str:
        suffix = Path(urlparse(url).path).suffix or ".bin"
        safe_hash = content_hash or hashlib.sha256(url.encode("utf-8")).hexdigest()
        path = self._raw_root() / self.source.id / f"{safe_hash[:16]}{suffix[:12]}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)

    def blocked(self, reason: str) -> ConnectorResult:
        return ConnectorResult(status="blocked", notes=[reason])

    def manual_only(self, reason: str) -> ConnectorResult:
        return ConnectorResult(status="manual_import", notes=[reason])


def rows_to_json_hash(rows: Iterable[dict[str, Any]]) -> str:
    content = json.dumps(list(rows), sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(content).hexdigest()
