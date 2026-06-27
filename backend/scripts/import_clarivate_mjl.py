from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.models.user import User
from crawler.connectors.clarivate import (
    SUPPORTED_CLARIVATE_IMPORT_SUFFIXES,
    clarivate_import_dir,
    list_clarivate_import_files,
    read_clarivate_records,
)
from crawler.scheduler import crawl_scheduler


def validate_clarivate_file(path: Path) -> dict[str, int]:
    if not path.exists():
        raise ValueError(f"Input file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Input path is not a file: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_CLARIVATE_IMPORT_SUFFIXES:
        allowed = ", ".join(sorted(SUPPORTED_CLARIVATE_IMPORT_SUFFIXES))
        raise ValueError(f"Unsupported Clarivate import file type: {suffix or '<none>'}. Use one of: {allowed}")
    rows, records = read_clarivate_records(path)
    if not rows:
        raise ValueError(f"File has no tabular rows: {path}")
    if not records:
        raise ValueError(f"File did not yield any recognizable Clarivate journal rows: {path}")
    return {"rows": len(rows), "recognized_records": len(records)}


def stage_clarivate_file(source: Path, *, replace_existing: bool = False) -> Path:
    target_dir = clarivate_import_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    if replace_existing:
        existing_files, _unsupported = list_clarivate_import_files(target_dir)
        for existing in existing_files:
            existing.unlink()
    target = target_dir / source.name
    shutil.copy2(source, target)
    return target


def ensure_crawler_user(db) -> User:
    user = db.query(User).filter(User.email == "crawler@aira.local").first()
    if user is None:
        user = User(email="crawler@aira.local", full_name="Crawler Runner", hashed_password="disabled")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def run_clarivate_crawl() -> dict[str, object]:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = ensure_crawler_user(db)
        job = crawl_scheduler.run_crawl_job(
            db,
            current_user=user,
            source_slugs=["clarivate_mjl"],
            include_bootstrap=False,
            include_live_sources=True,
        )
        return {
            "job_id": job.id,
            "job_status": job.status.value,
            "records_seen": job.records_seen,
            "records_created": job.records_created,
            "records_updated": job.records_updated,
            "records_indexed": job.records_indexed,
            "error_message": job.error_message,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage a user-downloaded Clarivate MJL file for crawler import.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input")
    group.add_argument("--sync-api", action="store_true", help="Use the official Clarivate Journals API instead of a local file.")
    parser.add_argument("--replace-existing", action="store_true", help="Remove previously staged CSV/XLSX files first.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and summarize the file without copying it.")
    parser.add_argument("--run-crawl", action="store_true", help="Run the clarivate_mjl crawl after staging succeeds.")
    args = parser.parse_args()

    if args.sync_api:
        payload: dict[str, object] = {
            "sync_api": True,
            "configured": bool(settings.clarivate_api_key),
            "api_url": settings.clarivate_journals_api_url,
            "editions": settings.clarivate_api_editions,
            "jcr_year": settings.clarivate_api_jcr_year,
        }
        if not settings.clarivate_api_key:
            raise SystemExit("CLARIVATE_API_KEY is not configured.")
        if args.dry_run:
            print(json.dumps(payload, indent=2, ensure_ascii=True))
            return 0
        payload["crawl"] = run_clarivate_crawl()
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        return 0

    source = Path(str(args.input))
    try:
        summary = validate_clarivate_file(source)
    except ValueError as exc:
        raise SystemExit(str(exc))

    payload: dict[str, object] = {
        "input": str(source),
        "rows": summary["rows"],
        "recognized_records": summary["recognized_records"],
        "target_dir": str(clarivate_import_dir()),
        "dry_run": bool(args.dry_run),
    }

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        return 0

    staged = stage_clarivate_file(source, replace_existing=args.replace_existing)
    payload["staged"] = str(staged)
    payload["replace_existing"] = bool(args.replace_existing)

    if args.run_crawl:
        payload["crawl"] = run_clarivate_crawl()

    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
