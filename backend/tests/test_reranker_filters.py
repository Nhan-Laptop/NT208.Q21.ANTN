from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.models.match_request import MatchRequest
from app.services.journal_match.filters import match_filters
from app.services.journal_match.reranker import match_reranker


class RerankerAndFilterTest(unittest.TestCase):
    def test_filters_reject_incompatible_candidates(self) -> None:
        request = MatchRequest(
            manuscript_id="m1",
            user_id="u1",
            desired_venue_type="journal",
            min_quartile="Q2",
            require_scopus=True,
            apc_budget_usd=1200,
            max_review_weeks=10,
        )
        expired_deadline = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        candidates = [
            {
                "record_id": "venue:good",
                "metadata": {
                    "entity_type": "venue",
                    "venue_type": "journal",
                    "indexed_scopus": True,
                    "sjr_quartile": "Q1",
                    "apc_usd": 500,
                    "avg_review_weeks": 8,
                },
            },
            {
                "record_id": "cfp:expired",
                "metadata": {
                    "entity_type": "cfp",
                    "venue_type": "conference",
                    "indexed_scopus": False,
                    "sjr_quartile": "Q4",
                    "apc_usd": 2500,
                    "avg_review_weeks": 20,
                    "full_paper_deadline": expired_deadline,
                },
            },
        ]
        accepted, diagnostics = match_filters.apply(request, candidates)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(diagnostics["accepted_count"], 1)
        self.assertIn("deadline_expired", diagnostics["rejected"][0]["reasons"])
        self.assertIn("missing_scopus", diagnostics["rejected"][0]["reasons"])

    def test_filters_reject_missing_quartile_when_min_quartile_is_requested(self) -> None:
        request = MatchRequest(manuscript_id="m1", user_id="u1", min_quartile="Q2")
        candidates = [
            {
                "record_id": "article:missing-quartile",
                "metadata": {
                    "entity_type": "article",
                    "venue_type": "journal",
                    "indexed_scopus": True,
                },
            }
        ]
        accepted, diagnostics = match_filters.apply(request, candidates)
        self.assertEqual(accepted, [])
        self.assertEqual(diagnostics["rejected"][0]["reasons"], ["missing_quartile"])

    def test_reranker_prefers_stronger_scope_and_policy_fit(self) -> None:
        request = MatchRequest(manuscript_id="m1", user_id="u1", apc_budget_usd=1500, max_review_weeks=12)
        candidates = [
            {
                "record_id": "venue:strong",
                "retrieval_score": 0.85,
                "document": "scientific retrieval biomedical NLP ranking reproducibility graph learning",
                "metadata": {
                    "entity_type": "venue",
                    "sjr_quartile": "Q1",
                    "citescore": 12.0,
                    "is_open_access": True,
                    "apc_usd": 900,
                    "avg_review_weeks": 8,
                    "indexed_scopus": True,
                    "indexed_wos": True,
                },
            },
            {
                "record_id": "venue:weak",
                "retrieval_score": 0.80,
                "document": "mathematics pedagogy classroom assessment",
                "metadata": {
                    "entity_type": "venue",
                    "sjr_quartile": "Q4",
                    "citescore": 1.0,
                    "is_open_access": False,
                    "apc_usd": 3000,
                    "avg_review_weeks": 24,
                    "indexed_scopus": False,
                    "indexed_wos": False,
                },
            },
        ]
        ranked = match_reranker.rerank(
            request=request,
            manuscript_text="scientific retrieval biomedical NLP ranking reproducibility graph learning",
            readiness_score=0.8,
            candidates=candidates,
        )
        self.assertEqual(ranked[0]["record_id"], "venue:strong")
        self.assertGreater(ranked[0]["score_breakdown"]["final_score"], ranked[1]["score_breakdown"]["final_score"])
        self.assertLess(ranked[0]["score_breakdown"]["penalty_score"], ranked[1]["score_breakdown"]["penalty_score"])


if __name__ == "__main__":
    unittest.main()
