from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
import re

from sqlalchemy import create_engine, inspect

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import models  # noqa: F401
from app.core.config import normalize_database_url
from app.core.database import Base


class MigrationSmokeTest(unittest.TestCase):
    @staticmethod
    def _extract_revision_fields(path: Path) -> tuple[str | None, str | None]:
        source = path.read_text(encoding="utf-8")
        revision_match = re.search(r'^revision\s*=\s*"([^"]+)"', source, re.MULTILINE)
        down_revision_match = re.search(r'^down_revision\s*=\s*(?:"([^"]+)"|None)', source, re.MULTILINE)
        revision = revision_match.group(1) if revision_match else None
        down_revision = None
        if down_revision_match:
            down_revision = down_revision_match.group(1)
        return revision, down_revision

    def test_migration_chain_and_metadata_schema(self) -> None:
        versions_root = BACKEND_ROOT / "alembic" / "versions"
        core_path = versions_root / "20260417_00_add_core_chat_tables.py"
        academic_path = versions_root / "20260417_01_add_academic_platform.py"
        ai_rules_path = versions_root / "20260617_01_add_ai_detection_rules.py"
        venue_source_url_path = versions_root / "20260627_01_add_venue_source_url.py"
        core_revision, core_down_revision = self._extract_revision_fields(core_path)
        academic_revision, academic_down_revision = self._extract_revision_fields(academic_path)
        ai_rules_revision, ai_rules_down_revision = self._extract_revision_fields(ai_rules_path)
        venue_source_revision, venue_source_down_revision = self._extract_revision_fields(venue_source_url_path)

        self.assertEqual(core_revision, "20260417_00")
        self.assertIsNone(core_down_revision)
        self.assertEqual(academic_revision, "20260417_01")
        self.assertEqual(academic_down_revision, "20260417_00")
        self.assertEqual(ai_rules_revision, "20260617_01")
        self.assertEqual(ai_rules_down_revision, "20260603_01")
        self.assertEqual(venue_source_revision, "20260627_01")
        self.assertEqual(venue_source_down_revision, "20260617_01")
        self.assertIn('sa.Enum("admin", "researcher"', core_path.read_text(encoding="utf-8"))
        self.assertIn('sa.Enum("pending", "running", "succeeded", "failed"', academic_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metadata.sqlite3"
            engine = create_engine(f"sqlite:///{db_path}")
            Base.metadata.create_all(engine)
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            self.assertTrue({"users", "chat_sessions", "file_attachments", "manuscripts", "match_requests", "crawl_jobs", "venues", "ai_detection_rules"}.issubset(tables))
            model_enums = {
                (table.name, column.name): list(column.type.enums)
                for table in Base.metadata.tables.values()
                for column in table.columns
                if hasattr(column.type, "enums")
            }
            venue_columns = {column["name"] for column in inspector.get_columns("venues")}
            self.assertEqual(model_enums[("users", "role")], ["admin", "researcher"])
            self.assertEqual(model_enums[("ai_detection_rules", "rule_type")], ["phrase", "regex", "semantic", "hybrid"])
            self.assertEqual(model_enums[("ai_detection_rules", "scope")], ["user", "global"])
            self.assertEqual(model_enums[("crawl_jobs", "status")], ["pending", "running", "succeeded", "failed"])
            self.assertEqual(model_enums[("venues", "venue_type")], ["journal", "conference", "workshop", "cfp"])
            self.assertEqual(model_enums[("match_requests", "status")], ["pending", "running", "succeeded", "failed"])
            self.assertIn("source_url", venue_columns)

            crawl_job_indexes = {index["name"] for index in inspector.get_indexes("crawl_jobs")}
            match_request_indexes = {index["name"] for index in inspector.get_indexes("match_requests")}
            ai_rule_indexes = {index["name"] for index in inspector.get_indexes("ai_detection_rules")}
            raw_snapshot_unique = {constraint["name"] for constraint in inspector.get_unique_constraints("raw_source_snapshots")}
            self.assertIn("ix_crawl_jobs_status", crawl_job_indexes)
            self.assertIn("ix_match_requests_status", match_request_indexes)
            self.assertIn("ix_ai_detection_rules_owner_enabled", ai_rule_indexes)
            self.assertIn("ix_ai_detection_rules_scope_enabled", ai_rule_indexes)
            self.assertIn("uq_raw_snapshot_source_external_content", raw_snapshot_unique)
            engine.dispose()

    def test_relative_sqlite_urls_are_normalized_against_backend_root(self) -> None:
        expected = f"sqlite:///{(BACKEND_ROOT / 'aira.db').resolve().as_posix()}"
        self.assertEqual(normalize_database_url("sqlite:///./aira.db"), expected)
        self.assertEqual(normalize_database_url("sqlite:///relative/nested.sqlite3"), f"sqlite:///{(BACKEND_ROOT / 'relative' / 'nested.sqlite3').resolve().as_posix()}")
        self.assertEqual(normalize_database_url("sqlite:///:memory:"), "sqlite:///:memory:")


if __name__ == "__main__":
    unittest.main()
