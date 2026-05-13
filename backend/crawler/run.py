#!/usr/bin/env python3
"""Run the academic crawl and indexing pipeline."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure backend/ is on sys.path when run directly
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    from app.core.database import Base, SessionLocal, engine
    from app.models.user import User
    from crawler.scheduler import crawl_scheduler

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "crawler@aira.local").first()
        if user is None:
            user = User(email="crawler@aira.local", full_name="Crawler Runner", hashed_password="disabled")
            db.add(user)
            db.commit()
            db.refresh(user)
        job = crawl_scheduler.run_crawl_job(
            db,
            current_user=user,
            include_bootstrap=True,
            include_live_sources=True,
        )
        logger.info(
            "Crawl complete status=%s seen=%d created=%d updated=%d indexed=%d",
            job.status,
            job.records_seen,
            job.records_created,
            job.records_updated,
            job.records_indexed,
        )
        print(
            f"Crawl job {job.id} completed with status={job.status} "
            f"seen={job.records_seen} indexed={job.records_indexed}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
