from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from crawler.connectors.base import (
    ConnectorRecord,
    ConnectorResult,
    ScholarlyConnector,
    SnapshotInfo,
    clean_text,
    first_value,
    read_tabular_rows,
    sha256_bytes,
    split_list,
)

SUPPORTED_CLARIVATE_IMPORT_SUFFIXES = {".csv", ".xlsx"}
CLARIVATE_API_PAGE_LIMIT = 50


def clarivate_import_dir() -> Path:
    import_dir = Path(settings.clarivate_manual_import_dir)
    if not import_dir.is_absolute():
        import_dir = Path(__file__).resolve().parents[2] / import_dir
    return import_dir


def list_clarivate_import_files(import_dir: Path | None = None) -> tuple[list[Path], list[Path]]:
    target_dir = import_dir or clarivate_import_dir()
    if not target_dir.exists():
        return [], []
    files = sorted(path for path in target_dir.glob("*") if path.is_file())
    supported = [path for path in files if path.suffix.lower() in SUPPORTED_CLARIVATE_IMPORT_SUFFIXES]
    unsupported = [path for path in files if path.suffix.lower() not in SUPPORTED_CLARIVATE_IMPORT_SUFFIXES]
    return supported, unsupported


def read_clarivate_records(path: Path) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    content = path.read_bytes()
    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if path.suffix.lower() == ".xlsx" else "text/csv"
    rows = read_tabular_rows(content, content_type, str(path))
    return rows, parse_clarivate_rows(rows, str(path))


def _coerce_metric_number(value: Any) -> float | None:
    if value is None:
        return None
    text = clean_text(str(value))
    if not text:
        return None
    normalized = text.replace(",", "")
    try:
        return float(normalized)
    except ValueError:
        return None


def _clarivate_subjects(categories: Any) -> list[str]:
    raw_values = categories
    if isinstance(categories, dict):
        raw_values = categories.get("value")
    if not isinstance(raw_values, list):
        return []
    subjects: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        if isinstance(item, dict):
            candidate = item.get("name") or item.get("category") or item.get("label") or item.get("value")
        else:
            candidate = item
        cleaned = clean_text(str(candidate or ""))
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            subjects.append(cleaned)
    return subjects


def parse_clarivate_api_hit(hit: dict[str, Any], source_url: str) -> dict[str, Any] | None:
    title = clean_text(str(hit.get("name") or ""))
    if not title:
        return None

    publisher = hit.get("publisher") if isinstance(hit.get("publisher"), dict) else {}
    open_access = hit.get("open_access") if isinstance(hit.get("open_access"), dict) else {}
    report = hit.get("journal_citation_reports") if isinstance(hit.get("journal_citation_reports"), dict) else {}
    metrics = hit.get("metrics") if isinstance(hit.get("metrics"), dict) else {}
    impact_metrics = metrics.get("impact_metrics") if isinstance(metrics.get("impact_metrics"), dict) else {}
    source_metrics = metrics.get("source_metrics") if isinstance(metrics.get("source_metrics"), dict) else {}
    ranks = hit.get("ranks") if isinstance(hit.get("ranks"), dict) else {}
    jif_ranks = ranks.get("jif") if isinstance(ranks.get("jif"), list) else []
    jci_ranks = ranks.get("jci") if isinstance(ranks.get("jci"), list) else []

    aliases = [clean_text(str(hit.get("jcr_title") or "")), clean_text(str(hit.get("iso_title") or ""))]
    aliases = [alias for alias in aliases if alias and alias.lower() != title.lower()]

    metric_entries: list[dict[str, Any]] = []
    jif_value = _coerce_metric_number(impact_metrics.get("jif"))
    if jif_value is not None:
        metric_entries.append({"metric_name": "Journal Impact Factor", "metric_value": jif_value})
    jci_value = _coerce_metric_number(impact_metrics.get("jci"))
    if jci_value is not None:
        metric_entries.append({"metric_name": "Journal Citation Indicator", "metric_value": jci_value})
    jif_percentile = _coerce_metric_number(source_metrics.get("jif_percentile"))
    if jif_percentile is not None:
        metric_entries.append({"metric_name": "JIF percentile", "metric_value": jif_percentile})

    jif_quartile = None
    if jif_ranks:
        jif_quartile = clean_text(str(jif_ranks[0].get("quartile") or ""))
        for rank in jif_ranks[:5]:
            category = clean_text(str(rank.get("category") or ""))
            quartile = clean_text(str(rank.get("quartile") or ""))
            if category or quartile:
                metric_entries.append(
                    {
                        "metric_name": "JIF rank",
                        "metric_text": f"{category}: {quartile}".strip(": "),
                    }
                )
    if jci_ranks:
        for rank in jci_ranks[:5]:
            category = clean_text(str(rank.get("category") or ""))
            quartile = clean_text(str(rank.get("quartile") or ""))
            if category or quartile:
                metric_entries.append(
                    {
                        "metric_name": "JCI rank",
                        "metric_text": f"{category}: {quartile}".strip(": "),
                    }
                )

    open_access_start_year = open_access.get("start_year")
    open_access_end_year = open_access.get("end_year")
    is_open_access = open_access_start_year is not None or open_access_end_year is not None

    return {
        "title": title,
        "canonical_title": title,
        "venue_type": "journal",
        "issn_print": clean_text(str(hit.get("issn") or "")) or None,
        "issn_electronic": clean_text(str(hit.get("e_issn") or "")) or None,
        "publisher": clean_text(str(publisher.get("name") or "")) or None,
        "country": clean_text(str(publisher.get("country_region") or "")) or None,
        "language": clean_text(str(hit.get("language") or "")) or None,
        "subjects": _clarivate_subjects(hit.get("categories")),
        "indexed_wos": True,
        "is_open_access": is_open_access,
        "source_url": clean_text(str(hit.get("self") or report.get("url") or source_url)),
        "homepage_url": clean_text(str(hit.get("self") or "")) or None,
        "source_name": "Clarivate Web of Science Journals API",
        "source_external_id": clean_text(str(hit.get("id") or hit.get("issn") or title)),
        "aliases": aliases,
        "jcr_quartile": jif_quartile or None,
        "metric_year": report.get("year"),
        "metrics": metric_entries,
    }


def parse_clarivate_rows(rows: list[dict[str, Any]], source_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        title = first_value(row, "Journal title", "Journal Title", "Title", "Full Journal Title")
        if not title:
            continue
        records.append(
            {
                "title": title,
                "canonical_title": title,
                "venue_type": "journal",
                "issn_print": first_value(row, "ISSN"),
                "issn_electronic": first_value(row, "eISSN", "EISSN"),
                "publisher": first_value(row, "Publisher"),
                "country": first_value(row, "Country"),
                "subjects": split_list(first_value(row, "Category", "Subject Category", "Web of Science Categories")),
                "indexed_wos": True,
                "jcr_quartile": first_value(row, "JCR Quartile"),
                "source_url": source_url,
                "source_name": "Clarivate Master Journal List",
                "source_external_id": first_value(row, "ISSN") or title,
                "metrics": [{"metric_name": "Web of Science collection", "metric_text": first_value(row, "Collection", "Index")}],
            }
        )
    return records


class ClarivateConnector(ScholarlyConnector):
    connector_id = "clarivate"

    def run(self) -> ConnectorResult:
        api_result = self._run_api_import()
        if api_result is not None:
            if api_result.records:
                return api_result
            if api_result.status != "failed":
                manual_result = self._run_manual_import()
                if manual_result.records:
                    manual_result.notes = api_result.notes + manual_result.notes
                    manual_result.snapshots = api_result.snapshots + manual_result.snapshots
                    return manual_result
                if api_result.status == "manual_import":
                    return manual_result
                if manual_result.status == "manual_import":
                    api_result.notes.extend(manual_result.notes)
                return api_result
        return self._run_manual_import()

    def _run_manual_import(self) -> ConnectorResult:
        import_dir = clarivate_import_dir()
        files, unsupported_files = list_clarivate_import_files(import_dir)
        if not files:
            reason = (
                "Clarivate MJL downloads require registration/login in normal operation. "
                f"Place user-downloaded CSV/XLSX files in {import_dir} for manual import."
            )
            if unsupported_files:
                suffixes = ", ".join(sorted({path.suffix.lower() or "<none>" for path in unsupported_files}))
                reason += f" Unsupported staged files were ignored: {suffixes}."
            return self.manual_only(reason)
        result = ConnectorResult()
        if unsupported_files:
            ignored = ", ".join(path.name for path in unsupported_files[:5])
            result.notes.append(f"Ignored unsupported Clarivate import files: {ignored}")
        for path in files:
            content = path.read_bytes()
            snapshot = SnapshotInfo(
                source_id=self.source.id,
                url=str(path),
                fetched_at=self.fetch_timestamp(),
                status_code=None,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if path.suffix.lower() != ".csv" else "text/csv",
                content_length=len(content),
                content_hash=sha256_bytes(content),
                storage_path=str(path),
                parser_version="clarivate-manual-import-v2",
                crawl_run_id=self.crawl_run_id,
            )
            result.snapshots.append(snapshot)
            _rows, payloads = read_clarivate_records(path)
            if not payloads:
                result.notes.append(f"No recognizable Clarivate journal rows found in {path.name}")
            for payload in payloads[: self.limit]:
                result.records.append(ConnectorRecord("venue", payload, snapshot))
        return result

    def _run_api_import(self) -> ConnectorResult | None:
        api_key = settings.clarivate_api_key
        if not api_key:
            return None

        result = ConnectorResult(notes=["Using Clarivate official Journals API sync."])
        page = 1
        remaining = self.limit

        while True:
            request_limit = CLARIVATE_API_PAGE_LIMIT if remaining is None else max(1, min(CLARIVATE_API_PAGE_LIMIT, remaining))
            payload, snapshot = self._fetch_api_page(page=page, page_limit=request_limit)
            result.snapshots.append(snapshot)
            if snapshot.error_message:
                result.status = "blocked"
                result.notes.append(f"Clarivate API request failed on page {page}: {snapshot.error_message}")
                return result

            hits = payload.get("hits")
            if not isinstance(hits, list):
                result.status = "blocked"
                result.notes.append("Clarivate API returned an unexpected payload shape.")
                return result

            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                payload_row = parse_clarivate_api_hit(hit, snapshot.url)
                if payload_row is None:
                    continue
                result.records.append(ConnectorRecord("venue", payload_row, snapshot))
                if remaining is not None:
                    remaining -= 1
                    if remaining <= 0:
                        return result

            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            total = metadata.get("total")
            current_page = metadata.get("page") or page
            current_limit = metadata.get("limit") or request_limit
            try:
                total_int = int(total) if total is not None else None
                current_page_int = int(current_page)
                current_limit_int = int(current_limit)
            except (TypeError, ValueError):
                total_int = None
                current_page_int = page
                current_limit_int = request_limit

            if not hits:
                return result
            if total_int is not None and current_page_int * current_limit_int >= total_int:
                return result
            page += 1

    def _fetch_api_page(self, *, page: int, page_limit: int) -> tuple[dict[str, Any], SnapshotInfo]:
        base_url = settings.clarivate_journals_api_url.rstrip("/")
        url = f"{base_url}/journals"
        params: dict[str, Any] = {
            "page": page,
            "limit": page_limit,
        }
        if settings.clarivate_api_editions:
            params["edition"] = settings.clarivate_api_editions
        if settings.clarivate_api_jcr_year is not None:
            params["jcrYear"] = settings.clarivate_api_jcr_year

        fetched_at = self.fetch_timestamp()
        try:
            with httpx.Client(timeout=settings.crawler_timeout_seconds, follow_redirects=True) as client:
                response = client.get(
                    url,
                    params=params,
                    headers={
                        "X-ApiKey": str(settings.clarivate_api_key),
                        "Accept": "application/json",
                        "User-Agent": settings.crawler_user_agent,
                    },
                )
            content = response.content
            content_hash = sha256_bytes(content)
            storage_path = self._write_snapshot(str(response.url), content, content_hash) if content else None
            error_message = None
            payload: dict[str, Any] = {}
            if response.status_code >= 400:
                error_message = f"http_{response.status_code}"
                try:
                    payload = response.json()
                    error = payload.get("error")
                    if isinstance(error, dict) and error.get("details"):
                        error_message = f"{error_message}: {error['details']}"
                    elif payload.get("error_description"):
                        error_message = f"{error_message}: {payload['error_description']}"
                except Exception:
                    payload = {}
            else:
                payload = response.json()
            snapshot = SnapshotInfo(
                source_id=self.source.id,
                url=str(response.url),
                fetched_at=fetched_at,
                status_code=response.status_code,
                content_type=response.headers.get("content-type"),
                content_length=len(content),
                content_hash=content_hash,
                storage_path=storage_path,
                error_message=error_message,
                parser_version="clarivate-official-api-v1",
                crawl_run_id=self.crawl_run_id,
            )
            return payload, snapshot
        except Exception as exc:
            snapshot = SnapshotInfo(
                source_id=self.source.id,
                url=url,
                fetched_at=fetched_at,
                status_code=None,
                content_type=None,
                content_length=None,
                content_hash=None,
                storage_path=None,
                error_message=str(exc),
                parser_version="clarivate-official-api-v1",
                crawl_run_id=self.crawl_run_id,
            )
            return {}, snapshot

    @staticmethod
    def fetch_timestamp() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()
