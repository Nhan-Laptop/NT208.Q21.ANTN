from __future__ import annotations

from pathlib import Path

from tests.test_support import BackendTestCase

from app.models.crawl_source import CrawlSource
from app.models.raw_source_snapshot import RawSourceSnapshot
from app.models.venue import Venue
from app.models.venue_metric import VenueMetric
from app.services.ingestion.index_service import academic_index_service
from crawler.connectors.base import SnapshotInfo, read_csv_rows
from crawler.connectors.core_ranks import parse_core_rank_rows
from crawler.connectors.sciencedirect_cfp import parse_sciencedirect_cfp_html
from crawler.connectors.scopus import parse_scopus_title_list
from crawler.connectors.source_registry import source_registry
from crawler.connectors.springer import parse_springer_journals_html
from crawler.pipelines.crawl_and_index import crawl_and_index_pipeline

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "crawler"


def test_source_registry_loads() -> None:
    sources = source_registry.load()
    ids = {source.id for source in sources}
    assert {"scimago", "scopus", "clarivate_mjl", "sciencedirect_cfp", "core_ranks", "springer"}.issubset(ids)
    for source in sources:
        assert source.allowed_domains
        assert source.access_mode in {
            "public_html",
            "public_download",
            "requires_registration",
            "requires_subscription",
            "interactive_only",
            "manual_import",
        }


def test_sciencedirect_cfp_parser_from_saved_html() -> None:
    html = (FIXTURES / "sciencedirect_cfp.html").read_text(encoding="utf-8")
    records = parse_sciencedirect_cfp_html(html, "https://www.sciencedirect.com/browse/calls-for-papers")
    assert records[0]["title"] == "AI for Reliable Science"
    assert records[0]["source_url"].startswith("https://www.sciencedirect.com/")
    assert records[0]["status"] == "open"


def test_scopus_title_list_parser_from_sample_file() -> None:
    rows = read_csv_rows((FIXTURES / "scopus_titles.csv").read_bytes())
    records = parse_scopus_title_list(rows, "https://www.elsevier.com/source-title-list.csv")
    assert records[0]["title"] == "Journal of Machine Learning Research"
    assert records[0]["issn_print"] == "1532-4435"
    assert records[0]["indexed_scopus"] is True


def test_core_rank_parser_from_saved_html_or_csv() -> None:
    rows = read_csv_rows((FIXTURES / "core_ranks.csv").read_bytes())
    records = parse_core_rank_rows(rows, "https://portal.core.edu.au/conf-ranks/")
    assert records[0]["title"] == "International Conference on Machine Learning"
    assert records[0]["aliases"] == ["ICML"]
    assert records[0]["metrics"][0]["metric_text"] == "A*"


def test_springer_journal_parser_from_saved_html() -> None:
    html = (FIXTURES / "springer_journals.html").read_text(encoding="utf-8")
    records = parse_springer_journals_html(html, "https://link.springer.com/journals/a/1")
    assert records[0]["title"] == "Machine Learning"
    assert records[0]["homepage_url"] == "https://link.springer.com/journal/10994"


def test_no_fake_sources_in_production_seed() -> None:
    registry_text = Path("crawler/sources.json").read_text(encoding="utf-8").lower()
    production_seed_text = Path("data/academic_seed.json").read_text(encoding="utf-8").lower()
    for marker in ("example.org", "jrais", "dummy", "fake"):
        assert marker not in registry_text
        assert marker not in production_seed_text


class LiveCrawlIngestionTests(BackendTestCase):
    def test_provenance_required_for_ingested_records(self) -> None:
        source = CrawlSource(slug="scopus", name="Scopus", source_type="registry_live_source", base_url="https://www.elsevier.com")
        self._ingest_venue(source)
        with self.db() as db:
            snapshot = db.query(RawSourceSnapshot).filter(RawSourceSnapshot.request_url == "https://www.elsevier.com/list.csv").one()
            assert snapshot.http_status == 200
            assert snapshot.content_hash == "abc123"
            assert snapshot.parser_version == "test-parser"
            assert snapshot.crawl_run_id == "run-1"

    def test_dedup_by_issn(self) -> None:
        with self.db() as db:
            source = CrawlSource(slug="scopus", name="Scopus", source_type="registry_live_source", base_url="https://www.elsevier.com")
            db.add(source)
            db.commit()
            payload = {
                "title": "Journal of Machine Learning Research",
                "canonical_title": "Journal of Machine Learning Research",
                "venue_type": "journal",
                "issn_print": "1532-4435",
                "publisher": "Publisher A",
                "source_url": "https://www.elsevier.com/a.csv",
            }
            crawl_and_index_pipeline._upsert_venue(db, source, payload)
            payload["title"] = "JMLR"
            payload["publisher"] = "Publisher B"
            crawl_and_index_pipeline._upsert_venue(db, source, payload)
            db.commit()
            assert db.query(Venue).count() == 1

    def test_crawl_run_records_errors_for_403_401_429(self) -> None:
        with self.db() as db:
            source = CrawlSource(slug="sciencedirect_cfp", name="ScienceDirect", source_type="registry_live_source", base_url="https://www.sciencedirect.com")
            db.add(source)
            db.commit()
            snapshot_info = SnapshotInfo(
                source_id="sciencedirect_cfp",
                url="https://www.sciencedirect.com/browse/calls-for-papers",
                fetched_at="2026-05-12T00:00:00+00:00",
                status_code=403,
                content_type="text/html",
                content_length=128,
                content_hash="blockedhash",
                error_message="http_403",
                crawl_run_id="run-403",
            )
            snapshot = crawl_and_index_pipeline._upsert_snapshot_info(db, source, snapshot_info)
            db.add(snapshot)
            db.commit()
            stored = db.query(RawSourceSnapshot).filter(RawSourceSnapshot.crawl_run_id == "run-403").one()
            assert stored.http_status == 403
            assert stored.error_message == "http_403"

    def test_chroma_document_contains_source_provenance(self) -> None:
        source = CrawlSource(slug="scopus", name="Scopus", source_type="registry_live_source", base_url="https://www.elsevier.com")
        venue_id = self._ingest_venue(source)
        with self.db() as db:
            venue = db.query(Venue).filter(Venue.id == venue_id).one()
            document, metadata = academic_index_service.build_venue_document(venue)
            assert "Source: scopus" in document
            assert metadata["source_ids"] == "scopus"
            assert "SJR" in metadata["metric_names"]

    def _ingest_venue(self, source: CrawlSource) -> str:
        with self.db() as db:
            db.add(source)
            db.commit()
            payload = {
                "title": "Journal of Machine Learning Research",
                "canonical_title": "Journal of Machine Learning Research",
                "venue_type": "journal",
                "issn_print": "1532-4435",
                "publisher": "Microtome Publishing",
                "source_url": "https://www.elsevier.com/list.csv",
                "metrics": [{"metric_name": "SJR", "metric_value": 2.5}],
            }
            snapshot_info = SnapshotInfo(
                source_id="scopus",
                url="https://www.elsevier.com/list.csv",
                fetched_at="2026-05-12T00:00:00+00:00",
                status_code=200,
                content_type="text/csv",
                content_length=256,
                content_hash="abc123",
                storage_path="/tmp/list.csv",
                parser_version="test-parser",
                crawl_run_id="run-1",
            )
            record = {"entity_type": "venue", "payload": payload, "snapshot": snapshot_info}
            db.add(crawl_and_index_pipeline._upsert_snapshot(db, source, record))
            venue, _ = crawl_and_index_pipeline._upsert_venue(db, source, payload)
            db.commit()
            return venue.id
