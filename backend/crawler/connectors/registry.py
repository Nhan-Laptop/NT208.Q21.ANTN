from __future__ import annotations

from crawler.connectors.base import ScholarlyConnector
from crawler.connectors.clarivate import ClarivateConnector
from crawler.connectors.core_ranks import CoreRanksConnector
from crawler.connectors.elsevier_journal_finder import ElsevierJournalFinderConnector
from crawler.connectors.ieee_publication_recommender import IEEEPublicationRecommenderConnector
from crawler.connectors.sciencedirect_cfp import ScienceDirectCFPConnector
from crawler.connectors.scimago import SCImagoConnector
from crawler.connectors.scopus import ScopusConnector
from crawler.connectors.source_registry import SourceConfig
from crawler.connectors.springer import SpringerConnector

CONNECTOR_CLASSES: dict[str, type[ScholarlyConnector]] = {
    "scimago": SCImagoConnector,
    "scopus": ScopusConnector,
    "clarivate": ClarivateConnector,
    "sciencedirect_cfp": ScienceDirectCFPConnector,
    "core_ranks": CoreRanksConnector,
    "springer": SpringerConnector,
    "elsevier_journal_finder": ElsevierJournalFinderConnector,
    "ieee_publication_recommender": IEEEPublicationRecommenderConnector,
}


def build_connector(source: SourceConfig, *, limit: int | None = None, download_only: bool = False, crawl_run_id: str | None = None) -> ScholarlyConnector:
    connector_cls = CONNECTOR_CLASSES.get(source.parser)
    if connector_cls is None:
        raise KeyError(f"Unsupported parser/connector: {source.parser}")
    return connector_cls(source, limit=limit, download_only=download_only, crawl_run_id=crawl_run_id)
