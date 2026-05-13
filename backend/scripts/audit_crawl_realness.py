from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal
from app.models.cfp_event import CFPEvent
from app.models.raw_source_snapshot import RawSourceSnapshot
from app.models.venue import Venue

FORBIDDEN_MARKERS = ("example.org", "localhost", "dummy", "fake", "sample", "jrais")


def _bad(value: str | None) -> bool:
    lowered = (value or "").lower()
    return any(marker in lowered for marker in FORBIDDEN_MARKERS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit crawled records for real provenance.")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()
    db = SessionLocal()
    try:
        snapshot_query = db.query(RawSourceSnapshot)
        if args.run_id:
            snapshot_query = snapshot_query.filter(RawSourceSnapshot.crawl_run_id == args.run_id)
        snapshots = snapshot_query.all()
        bad_venues = [venue.id for venue in db.query(Venue).all() if _bad(venue.homepage_url) or _bad(venue.title)]
        bad_cfps = [cfp.id for cfp in db.query(CFPEvent).all() if _bad(cfp.source_url) or _bad(cfp.title)]
        missing_provenance = [snapshot.id for snapshot in snapshots if not (snapshot.request_url or snapshot.storage_path) or not snapshot.content_hash]
        statuses = Counter(str(snapshot.http_status or snapshot.error_message or "file") for snapshot in snapshots)
        report = {
            "run_id": args.run_id,
            "snapshots": len(snapshots),
            "statuses": dict(statuses),
            "bad_venue_records": bad_venues,
            "bad_cfp_records": bad_cfps,
            "snapshots_missing_provenance": missing_provenance,
            "passed": not bad_venues and not bad_cfps and not missing_provenance,
        }
        print(json.dumps(report, indent=2, default=str))
        return 0 if report["passed"] else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
