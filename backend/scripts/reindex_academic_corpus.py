from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal
from app.models.user import User
from crawler.scheduler import crawl_scheduler


def main() -> int:
    parser = argparse.ArgumentParser(description="Reindex academic SQL corpus into Chroma.")
    parser.add_argument("--source", action="append", dest="sources")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        user = db.query(User).order_by(User.created_at.asc()).first()
        job = crawl_scheduler.run_reindex_job(db, current_user=user, source_slugs=args.sources)
        print(json.dumps({"job_id": job.id, "status": job.status.value, "indexed": job.records_indexed, "metadata": job.job_metadata}, indent=2, default=str))
        return 0 if job.status.value == "succeeded" else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
