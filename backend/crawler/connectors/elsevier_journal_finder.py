from __future__ import annotations

from crawler.connectors.base import ConnectorResult, ScholarlyConnector


class ElsevierJournalFinderConnector(ScholarlyConnector):
    connector_id = "elsevier_journal_finder"

    def run(self) -> ConnectorResult:
        return self.blocked(
            "Elsevier Journal Finder is an interactive recommender. No public bulk API is configured; do not batch scrape or fabricate recommendations."
        )
