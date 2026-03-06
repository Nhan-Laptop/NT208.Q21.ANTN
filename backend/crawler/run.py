#!/usr/bin/env python3
"""
Crawler Runner — scrape CFP data and seed the ChromaDB vector store.

Usage::

    cd backend/
    python -m crawler.run          # from backend/ directory
    # or
    python crawler/run.py          # direct execution
"""

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
    from crawler.universal_scraper import UniversalScraper
    from crawler.db_builder import seed_database

    logger.info("=== AIRA Crawler Pipeline ===")

    # Step 1: Scrape
    scraper = UniversalScraper()
    records = scraper.scrape_all()
    logger.info("Scraper returned %d REAL record(s).", len(records))

    if not records:
        print("\n⚠️  No real data scraped. Database is empty.\n")
        logger.warning("No real data scraped. Database will be empty.")

    # Step 2: Seed DB (always run — wipes stale data even if 0 records)
    count = seed_database(records)
    print(f"\n✅ Pipeline complete — {count} REAL record(s) ingested into ChromaDB.\n")
    logger.info("Pipeline complete — %d REAL document(s) in ChromaDB.", count)


if __name__ == "__main__":
    main()
