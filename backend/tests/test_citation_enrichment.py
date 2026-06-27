from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from app.services.tools.citation.sources.datacite import normalize_datacite_work
from app.services.tools.citation.sources.publisher_meta import PublisherMetaSource
from app.services.tools.citation_checker import CandidateWork, CitationCheckResult, CitationChecker


APA_NO_DOI_REAL = (
    "Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., "
    "Kaiser, L., & Polosukhin, I. (2017). Attention is all you need. "
    "Advances in Neural Information Processing Systems, 30, 5998-6008."
)


class _CitationTestSettings:
    def __init__(
        self,
        *,
        semantic_scholar_enabled: bool = False,
        semantic_scholar_api_key: str | None = None,
        semantic_scholar_fallback_threshold: float = 0.90,
    ) -> None:
        self.semantic_scholar_enabled = semantic_scholar_enabled
        self.semantic_scholar_api_key = semantic_scholar_api_key
        self.semantic_scholar_fallback_threshold = semantic_scholar_fallback_threshold


class CitationEnrichmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings_patch = patch(
            "app.services.tools.citation_checker.get_settings",
            return_value=_CitationTestSettings(semantic_scholar_enabled=False),
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def test_verify_doi_exact_uses_datacite_before_openalex(self) -> None:
        checker = CitationChecker()
        datacite_result = CitationCheckResult(
            citation="10.5555/datacite-test",
            status="DOI_VERIFIED",
            doi="10.5555/datacite-test",
            title="DataCite Test Record",
            authors=["Ada Lovelace"],
            year=2024,
            source="datacite_doi",
            confidence=0.92,
            metadata={
                "datacite": {
                    "id": "10.5555/datacite-test",
                    "attributes": {
                        "doi": "10.5555/datacite-test",
                        "titles": [{"title": "DataCite Test Record"}],
                        "creators": [{"name": "Ada Lovelace"}],
                        "publicationYear": 2024,
                        "publisher": "Zenodo",
                        "url": "https://example.org/datacite-test",
                    },
                }
            },
        )

        with (
            patch.object(checker, "_verify_doi_crossref", return_value=None),
            patch.object(checker, "_verify_doi_datacite_exact", return_value=datacite_result),
            patch.object(
                checker,
                "_verify_doi_openalex_exact",
                side_effect=AssertionError("OpenAlex must not run after a DataCite exact hit"),
            ),
        ):
            result = checker.verify_doi_exact("10.5555/datacite-test")

        self.assertEqual(result.source, "datacite_doi")
        self.assertEqual(result.matched_by, "doi_exact")
        self.assertEqual(result.resolver_chain, ["datacite_exact"])
        self.assertEqual(result.source_diagnostics["datacite"]["state"], "matched")
        self.assertEqual(result.matched_doi, "10.5555/datacite-test")

    def test_normalize_datacite_work_maps_core_fields(self) -> None:
        candidate = normalize_datacite_work(
            {
                "id": "10.5438/0012",
                "attributes": {
                    "doi": "10.5438/0012",
                    "titles": [
                        {"title": "DataCite Metadata Schema Documentation for the Publication and Citation of Research Data v4.0"}
                    ],
                    "creators": [{"name": "DataCite Metadata Working Group"}],
                    "publicationYear": 2016,
                    "publisher": "DataCite e.V.",
                    "url": "https://schema.datacite.org/meta/kernel-4.0/index.html",
                    "types": {"schemaOrg": "ScholarlyArticle"},
                },
            }
        )

        self.assertEqual(candidate.source, "datacite")
        self.assertEqual(candidate.doi, "10.5438/0012")
        self.assertEqual(candidate.year, 2016)
        self.assertEqual(candidate.venue, "DataCite e.V.")
        self.assertIn("DataCite Metadata Schema Documentation", candidate.title or "")
        self.assertEqual(candidate.authors, ["DataCite Metadata Working Group"])

    def test_publisher_meta_enrich_candidate_parses_meta_tags(self) -> None:
        html = """
        <html>
          <head>
            <meta name="citation_title" content="Attention Is All You Need" />
            <meta name="citation_doi" content="10.5555/attention" />
            <meta name="citation_author" content="Ashish Vaswani" />
            <meta name="citation_author" content="Noam Shazeer" />
            <meta name="citation_journal_title" content="NeurIPS Proceedings" />
            <meta name="citation_publication_date" content="2017-12-01" />
          </head>
        </html>
        """

        class FakeClient:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def get(self, url: str):
                return httpx.Response(
                    200,
                    text=html,
                    request=httpx.Request("GET", url),
                )

        source = PublisherMetaSource()
        candidate = CandidateWork(
            source="crossref",
            title="Attention Is All You Need",
            url="https://example.org/paper",
        )

        with patch("app.services.tools.citation.sources.publisher_meta.httpx.Client", FakeClient):
            enriched = source.enrich_candidate(candidate)

        self.assertEqual(enriched.resolved_url, "https://example.org/paper")
        self.assertEqual(enriched.doi, "10.5555/attention")
        self.assertEqual(enriched.year, 2017)
        self.assertEqual(enriched.venue, "NeurIPS Proceedings")
        self.assertEqual(enriched.authors, ["Ashish Vaswani", "Noam Shazeer"])
        self.assertTrue(enriched.raw.get("publisher_meta_confirmed"))

    def test_metadata_match_result_includes_evidence_chain_fields(self) -> None:
        checker = CitationChecker()
        base_candidate = CandidateWork(
            source="crossref",
            title="Attention is all you need",
            authors=[
                "vaswani",
                "shazeer",
                "parmar",
                "uszkoreit",
                "jones",
                "gomez",
                "kaiser",
                "polosukhin",
            ],
            year=2017,
            venue="Advances in Neural Information Processing Systems",
            doi="10.5555/attention",
            url="https://example.org/attention",
        )
        enriched_candidate = CandidateWork(
            **{
                **base_candidate.__dict__,
                "resolved_url": "https://publisher.example.org/attention",
                "evidence_urls": [
                    "https://publisher.example.org/attention",
                    "https://example.org/attention",
                ],
                "raw": {"publisher_meta_confirmed": True},
            }
        )

        with (
            patch("app.services.tools.citation_checker.search_crossref_candidates", return_value=[base_candidate]),
            patch("app.services.tools.citation_checker.search_openalex_candidates", return_value=[]),
            patch.object(
                checker,
                "_enrich_candidates_with_publisher_meta",
                return_value=([enriched_candidate], {"state": "matched", "candidate_count": 1, "detail": None}),
            ),
        ):
            result = checker._verify_metadata_match(
                {
                    "raw": APA_NO_DOI_REAL,
                    "type": "apa_reference",
                    "authors": ["vaswani"],
                    "year": 2017,
                    "doi": None,
                }
            )

        self.assertIn(result.status, {"METADATA_VERIFIED", "LIKELY_MATCH"})
        self.assertEqual(result.matched_by, "publisher_meta_confirmed")
        self.assertEqual(result.resolved_url, "https://publisher.example.org/attention")
        self.assertIn("https://publisher.example.org/attention", result.evidence_urls)
        self.assertIn("publisher_meta", result.resolver_chain)

