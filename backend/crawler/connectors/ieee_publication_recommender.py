from __future__ import annotations

from crawler.connectors.base import ConnectorResult, ScholarlyConnector


class IEEEPublicationRecommenderConnector(ScholarlyConnector):
    connector_id = "ieee_publication_recommender"

    def run(self) -> ConnectorResult:
        return self.blocked(
            "IEEE Publication Recommender is interactive_only without a configured public API. No bulk scrape is performed."
        )
