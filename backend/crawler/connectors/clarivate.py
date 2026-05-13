from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings
from crawler.connectors.base import ConnectorRecord, ConnectorResult, ScholarlyConnector, SnapshotInfo, first_value, read_tabular_rows, sha256_bytes, split_list


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
        import_dir = Path(settings.clarivate_manual_import_dir)
        if not import_dir.is_absolute():
            import_dir = Path(__file__).resolve().parents[2] / import_dir
        files = sorted([path for path in import_dir.glob("*") if path.suffix.lower() in {".csv", ".xlsx", ".xls"}])
        if not files:
            reason = (
                "Clarivate MJL downloads require registration/login in normal operation. "
                f"Place user-downloaded CSV/XLSX files in {import_dir} for manual import."
            )
            return self.manual_only(reason)
        result = ConnectorResult()
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
                parser_version="clarivate-manual-import-v1",
                crawl_run_id=self.crawl_run_id,
            )
            result.snapshots.append(snapshot)
            rows = read_tabular_rows(content, snapshot.content_type, str(path))
            for payload in parse_clarivate_rows(rows, str(path))[: self.limit]:
                result.records.append(ConnectorRecord("venue", payload, snapshot))
        return result

    @staticmethod
    def fetch_timestamp() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()
