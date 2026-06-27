from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.v1.endpoints.chat import create_completion
from app.core.config import settings
from app.models.chat_message import MessageRole, MessageType
from app.models.chat_session import SessionMode
from app.schemas.chat import ChatCompletionRequest
from app.services.academic_policy import AIRA_RESOLVED_RECORD_FOLLOWUP_PROMPT
from app.services.chat_service import chat_service
from app.services.external_academic_search import AuthorPublicationLookupResult, external_academic_search_service
from app.services.tools.citation import CandidateWork
from app.services.tools.citation_checker import CitationCheckResult

try:
    from .support import TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import TestEnvironment


PAPER_HEADER = """Is working memory domain-general or domain-specific?
Nazbanou Nozari1,2, Randi C. Martin3

1Department of Psychological and Brain Sciences, Indiana University, Bloomington, Indiana, USA
2Cognitive Science Program, Indiana University, Bloomington, Indiana, USA
3Department of Psychological Sciences, Rice University, Houston, Texas, USA
"""


class ExternalAcademicFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()

    def tearDown(self) -> None:
        self.env.close()

    def test_lookup_parses_paper_header_and_returns_external_match(self) -> None:
        crossref_candidate = CandidateWork(
            source="crossref",
            title="Is working memory domain-general or domain-specific?",
            authors=["Nazbanou Nozari", "Randi C. Martin"],
            year=2024,
            venue="Trends in Cognitive Sciences",
            doi="10.1016/j.tics.2024.06.006",
            url="https://doi.org/10.1016/j.tics.2024.06.006",
            volume="28",
            issue="11",
            pages="1023-1036",
            raw={
                "abstract": "Crossref abstract for working memory paper.",
                "container-title": ["Trends in Cognitive Sciences"],
                "subject": ["Cognitive psychology"],
            },
        )
        openalex_candidate = CandidateWork(
            source="openalex",
            title="Is working memory domain-general or domain-specific?",
            authors=["Nazbanou Nozari", "Randi C. Martin"],
            year=2024,
            venue="Trends in Cognitive Sciences",
            doi="10.1016/j.tics.2024.06.006",
            url="https://openalex.org/W1234567890",
            external_id="W1234567890",
            external_id_type="openalex",
            volume="28",
            issue="11",
            pages="1023-1036",
            raw={
                "abstract": "OpenAlex abstract for working memory paper.",
                "concepts": [{"display_name": "Cognitive psychology"}],
                "keywords": [{"display_name": "working memory"}],
                "primary_location": {"source": {"display_name": "Trends in Cognitive Sciences"}},
            },
        )
        pubmed_candidate = CandidateWork(
            source="pubmed",
            title="Is working memory domain-general or domain-specific?",
            authors=["Nozari N", "Martin RC"],
            year=2024,
            venue="Trends in Cognitive Sciences",
            doi="10.1016/j.tics.2024.06.006",
            url="https://pubmed.ncbi.nlm.nih.gov/39019705/",
            external_id="39019705",
            external_id_type="pmid",
            volume="28",
            issue="11",
            pages="1023-1036",
            pmid="39019705",
            pmcid="PMC11540753",
            raw={"fulljournalname": "Trends in Cognitive Sciences"},
        )

        object.__setattr__(settings, "enable_external_academic_search", True)
        object.__setattr__(settings, "crossref_enabled", True)
        object.__setattr__(settings, "openalex_enabled", True)
        object.__setattr__(settings, "pubmed_enabled", True)
        object.__setattr__(settings, "semantic_scholar_enabled", False)

        with self.env.session() as db:
            with (
                patch.object(
                    external_academic_search_service,
                    "_search_crossref",
                    return_value=([crossref_candidate], {"state": "matched", "candidate_count": 1, "detail": None}),
                ),
                patch.object(
                    external_academic_search_service,
                    "_search_openalex",
                    return_value=([openalex_candidate], {"state": "matched", "candidate_count": 1, "detail": None}),
                ),
                patch.object(
                    external_academic_search_service,
                    "_search_pubmed",
                    return_value=([pubmed_candidate], {"state": "matched", "candidate_count": 1, "detail": None}),
                ),
            ):
                result = external_academic_search_service.lookup(db, PAPER_HEADER)

        self.assertEqual(result.status, "external_found")
        self.assertTrue(result.external_search_used)
        self.assertIsNotNone(result.best_record)
        self.assertEqual(result.best_record["title"], "Is working memory domain-general or domain-specific?")
        self.assertEqual(result.best_record["source"], "Crossref")
        self.assertEqual(result.best_record["doi"], "10.1016/j.tics.2024.06.006")
        self.assertEqual(result.best_record["venue"], "Trends in Cognitive Sciences")
        self.assertEqual(result.best_record["pmid"], "39019705")
        self.assertEqual(result.best_record["pmcid"], "PMC11540753")
        self.assertIn("Resolved the lookup query from a pasted paper header", " ".join(result.notes))
        checked_names = [item["name"] for item in result.checked_sources]
        self.assertEqual(checked_names[:3], ["Internal academic database", "Crossref", "OpenAlex"])
        self.assertIn("PubMed", checked_names)
        self.assertIn("working memory", " ".join(str(item) for item in result.query_terms).lower())

    def test_lookup_rejects_low_confidence_false_positive(self) -> None:
        wrong_candidate = CandidateWork(
            source="crossref",
            title="Working Memory in Chinese Text Comprehension",
            authors=["Someone Else"],
            year=2021,
            venue="Psi Chi Journal of Psychological Research",
            doi="10.24839/2325-7342.jn26.1.26",
            url="https://doi.org/10.24839/2325-7342.jn26.1.26",
        )

        object.__setattr__(settings, "enable_external_academic_search", True)
        object.__setattr__(settings, "crossref_enabled", True)
        object.__setattr__(settings, "openalex_enabled", True)
        object.__setattr__(settings, "pubmed_enabled", False)
        object.__setattr__(settings, "semantic_scholar_enabled", False)

        with self.env.session() as db:
            with (
                patch.object(
                    external_academic_search_service,
                    "_search_crossref",
                    return_value=([wrong_candidate], {"state": "matched", "candidate_count": 1, "detail": None}),
                ),
                patch.object(
                    external_academic_search_service,
                    "_search_openalex",
                    return_value=([], {"state": "no_match", "candidate_count": 0, "detail": None}),
                ),
            ):
                result = external_academic_search_service.lookup(
                    db,
                    'tìm kiếm thông tin về bài báo sau: "Is working memory domain-general or domain-specific?"',
                )

        self.assertEqual(result.status, "low_confidence")
        self.assertIsNone(result.best_record)
        self.assertEqual(result.records, [])
        self.assertEqual(len(result.low_confidence_records), 1)
        self.assertEqual(result.low_confidence_records[0]["title"], "Working Memory in Chinese Text Comprehension")

    def test_lookup_keeps_strong_match_when_other_sources_degrade(self) -> None:
        crossref_candidate = CandidateWork(
            source="crossref",
            title="Is working memory domain-general or domain-specific?",
            authors=["Nazbanou Nozari", "Randi C. Martin"],
            year=2024,
            venue="Trends in Cognitive Sciences",
            doi="10.1016/j.tics.2024.06.006",
            url="https://doi.org/10.1016/j.tics.2024.06.006",
        )

        object.__setattr__(settings, "enable_external_academic_search", True)
        object.__setattr__(settings, "crossref_enabled", True)
        object.__setattr__(settings, "openalex_enabled", True)
        object.__setattr__(settings, "pubmed_enabled", False)
        object.__setattr__(settings, "semantic_scholar_enabled", True)

        with self.env.session() as db:
            with (
                patch.object(
                    external_academic_search_service,
                    "_search_crossref",
                    return_value=([crossref_candidate], {"state": "matched", "candidate_count": 1, "detail": None}),
                ),
                patch.object(
                    external_academic_search_service,
                    "_search_openalex",
                    return_value=([], {"state": "http_error", "candidate_count": 0, "detail": "HTTP 400"}),
                ),
                patch.object(
                    external_academic_search_service,
                    "_search_semantic_scholar",
                    return_value=([], {"state": "rate_limited", "candidate_count": 0, "detail": "HTTP 429"}),
                ),
            ):
                result = external_academic_search_service.lookup(db, PAPER_HEADER)

        self.assertEqual(result.status, "external_found")
        self.assertIsNotNone(result.best_record)
        self.assertEqual(result.best_record["title"], "Is working memory domain-general or domain-specific?")
        self.assertTrue(any("degraded" in note.lower() for note in result.notes))

    def test_author_publication_lookup_falls_back_to_external_sources_and_excludes_source_paper(self) -> None:
        object.__setattr__(settings, "enable_external_academic_search", True)
        object.__setattr__(settings, "openalex_enabled", True)
        object.__setattr__(settings, "crossref_enabled", False)

        source_record = {
            "title": "Array programming with NumPy",
            "authors": ["Stefan van der Walt"],
            "year": 2020,
            "venue": "Nature",
            "doi": "10.1038/s41586-020-2649-2",
            "source": "Crossref",
            "confidence": 1.0,
        }
        source_candidate = CandidateWork(
            source="openalex",
            title="Array programming with NumPy",
            authors=["Stefan van der Walt"],
            year=2020,
            venue="Nature",
            doi="10.1038/s41586-020-2649-2",
            url="https://openalex.org/Wsource",
        )
        other_candidate = CandidateWork(
            source="openalex",
            title="Python for scientific computing",
            authors=["Stefan van der Walt"],
            year=2021,
            venue="Computing in Science & Engineering",
            doi="10.1109/example.2021.1",
            url="https://openalex.org/Wother",
        )

        with self.env.session() as db:
            with patch.object(
                external_academic_search_service,
                "_search_openalex_author_works",
                return_value=(
                    [source_candidate, other_candidate],
                    {"state": "matched", "candidate_count": 2, "detail": "OpenAlex author works lookup returned candidates."},
                ),
            ):
                result = external_academic_search_service.lookup_author_publications(
                    db,
                    source_record=source_record,
                    authors=[
                        {
                            "name": "Stefan van der Walt",
                            "openalex_id": "A500000001",
                            "confidence": 0.98,
                            "notes": [],
                        }
                    ],
                    source_doi="10.1038/s41586-020-2649-2",
                    source_title="Array programming with NumPy",
                )

        self.assertEqual(result.status, "matched")
        self.assertTrue(result.external_search_used)
        self.assertEqual(len(result.authors), 1)
        publications = result.authors[0]["publications"]
        self.assertEqual(len(publications), 1)
        self.assertEqual(publications[0]["title"], "Python for scientific computing")
        self.assertEqual(publications[0]["doi"], "10.1109/example.2021.1")
        self.assertTrue(any("OpenAlex" == item["name"] for item in result.checked_sources))

    def test_author_publication_lookup_uses_web_search_fallback_when_primary_sources_do_not_match(self) -> None:
        object.__setattr__(settings, "enable_external_academic_search", True)
        object.__setattr__(settings, "openalex_enabled", False)
        object.__setattr__(settings, "crossref_enabled", False)
        object.__setattr__(settings, "web_search_provider", "generic_json")

        source_record = {
            "title": "Array programming with NumPy",
            "authors": ["Stefan van der Walt"],
            "year": 2020,
            "venue": "Nature",
            "doi": "10.1038/s41586-020-2649-2",
            "source": "Crossref",
            "confidence": 1.0,
        }
        verified_web_result = CitationCheckResult(
            citation="10.1109/example.2021.1",
            status="DOI_VERIFIED",
            doi="10.1109/example.2021.1",
            title="Python for scientific computing",
            authors=["Stefan van der Walt"],
            year=2021,
            source="crossref_doi",
            confidence=1.0,
            matched_doi="10.1109/example.2021.1",
            matched_title="Python for scientific computing",
            matched_authors=["Stefan van der Walt"],
            matched_year=2021,
            matched_venue="Computing in Science & Engineering",
            resolver_chain=["crossref_exact"],
            matched_by="doi_exact",
            evidence_urls=["https://doi.org/10.1109/example.2021.1"],
            metadata={"crossref": {"subject": ["Scientific computing"]}},
            completed_metadata={"url": "https://doi.org/10.1109/example.2021.1"},
        )

        with self.env.session() as db:
            with (
                patch.object(
                    external_academic_search_service,
                    "_search_internal_author_publications",
                    return_value=([], {"name": "Internal academic database", "state": "no_match", "candidate_count": 0, "detail": "No internal match."}),
                ),
                patch(
                    "app.services.external_academic_search._WEB_SEARCH_SOURCE.search_author_publications_with_context",
                    return_value=(
                        [
                            CandidateWork(
                                source="web_search",
                                title="Python for scientific computing",
                                doi="10.1109/example.2021.1",
                                url="https://example.org/python-scientific-computing",
                                raw={"doi_candidates": ["10.1109/example.2021.1"]},
                                evidence_urls=["https://example.org/python-scientific-computing"],
                                source_domain="example.org",
                            )
                        ],
                        {
                            "state": "matched",
                            "detail": None,
                            "query": "\"Stefan van der Walt\" publications",
                            "provider": "generic_json",
                        },
                    ),
                ),
                patch("app.services.external_academic_search.citation_checker.verify_doi_exact", return_value=verified_web_result),
            ):
                result = external_academic_search_service.lookup_author_publications(
                    db,
                    source_record=source_record,
                    authors=[{"name": "Stefan van der Walt", "confidence": 0.9, "notes": []}],
                    source_doi="10.1038/s41586-020-2649-2",
                    source_title="Array programming with NumPy",
                )

        self.assertEqual(result.status, "matched")
        self.assertTrue(result.external_search_used)
        self.assertEqual(result.authors[0]["publications"][0]["title"], "Python for scientific computing")
        self.assertTrue(any(item["name"] == "Web search" and item["state"] == "matched" for item in result.checked_sources))

    def test_named_author_followup_reuses_recent_doi_context(self) -> None:
        session = self.env.create_chat_session(user=self.user, mode=SessionMode.GENERAL_QA)
        with self.env.session() as db:
            chat_service._save_message(
                db=db,
                session_id=session.id,
                role=MessageRole.ASSISTANT,
                content="Prior DOI metadata",
                message_type=MessageType.TEXT,
                tool_results={
                    "type": "doi_metadata",
                    "status": "verified",
                    "data": {
                        "doi": "10.1038/s41586-020-2649-2",
                        "title": "Array programming with NumPy",
                        "authors": ["Stéfan J. van der Walt", "K. Jarrod Millman"],
                        "journal": "Nature",
                        "publisher": "Springer Nature",
                        "publication_year": 2020,
                        "verification_status": "Valid DOI",
                        "confidence": 1.0,
                        "source": "Crossref",
                        "missing_fields": [],
                        "notes": [],
                    },
                },
            )
            with patch(
                "app.services.chat_service.external_academic_search_service.lookup_author_publications",
                return_value=AuthorPublicationLookupResult(
                    status="matched",
                    source_record={
                        "title": "Array programming with NumPy",
                        "authors": ["Stéfan J. van der Walt", "K. Jarrod Millman"],
                        "year": 2020,
                        "venue": "Nature",
                        "doi": "10.1038/s41586-020-2649-2",
                        "source": "Crossref",
                        "confidence": 1.0,
                    },
                    authors=[
                        {
                            "name": "Stéfan J. van der Walt",
                            "checked_sources": [
                                {"name": "Internal academic database", "state": "no_match", "candidate_count": 0},
                                {"name": "OpenAlex", "state": "matched", "candidate_count": 1},
                            ],
                            "publications": [
                                {"title": "Python for scientific computing", "source": "OpenAlex", "confidence": 0.84}
                            ],
                        }
                    ],
                    external_search_used=True,
                    checked_sources=[
                        {"name": "Internal academic database", "state": "no_match", "candidate_count": 0},
                        {"name": "OpenAlex", "state": "matched", "candidate_count": 1},
                    ],
                    notes=[],
                ),
            ) as lookup:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=session.id,
                        user_message="publication khác của Stéfan J. van der Walt",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.tool_results["type"], "author_publication_search")
        self.assertTrue(response.assistant_message.tool_results["author"]["matched_from_context"])
        self.assertEqual(response.assistant_message.tool_results["source_doi"], "10.1038/s41586-020-2649-2")
        self.assertEqual(lookup.call_args.kwargs["source_doi"], "10.1038/s41586-020-2649-2")
        self.assertEqual(lookup.call_args.kwargs["source_title"], "Array programming with NumPy")

    def test_general_chat_reuses_latest_resolved_record_for_short_followup(self) -> None:
        session = self.env.create_chat_session(user=self.user, mode=SessionMode.GENERAL_QA)
        with self.env.session() as db:
            chat_service._save_message(
                db=db,
                session_id=session.id,
                role=MessageRole.ASSISTANT,
                content="Prior lookup",
                message_type=MessageType.TEXT,
                tool_results={
                    "type": "academic_lookup",
                    "status": "external_found",
                    "source_mode": "external_scholarly",
                    "confidence": 0.9,
                    "confidence_label": "High",
                    "external_search_used": True,
                    "checked_sources": [
                        {"name": "Internal academic database", "state": "no_match", "candidate_count": 0},
                        {"name": "OpenAlex", "state": "matched", "candidate_count": 1},
                    ],
                    "source_diagnostics": {},
                    "query_terms": ["working", "memory"],
                    "data": {
                        "records": [],
                        "count": 1,
                        "best_record": {
                            "title": "Is working memory domain-general or domain-specific?",
                            "authors": ["Nazbanou Nozari", "Randi C. Martin"],
                            "year": 2024,
                            "venue": "Psychonomic Bulletin & Review",
                            "source": "OpenAlex",
                            "confidence": 0.9,
                            "abstract": "This paper evaluates whether working memory is domain-general.",
                        },
                        "notes": [],
                        "internal_result": {"count": 0, "best_score": 0, "confidence": 0.0},
                    },
                },
            )
            mocked_response = Mock(text="Follow-up grounded answer", message_type="text", tool_results=None)
            with (
                patch("app.services.chat_service.external_academic_search_service.lookup", side_effect=AssertionError("lookup should not run")),
                patch("app.services.chat_service.gemini_service.generate_response", return_value=mocked_response) as generate,
            ):
                response = create_completion(
                    payload=ChatCompletionRequest(session_id=session.id, user_message="Bài này nói gì?"),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "text")
        self.assertEqual(response.assistant_message.content, "Follow-up grounded answer")
        call_kwargs = generate.call_args.kwargs
        self.assertEqual(call_kwargs["system_prompt_override"], AIRA_RESOLVED_RECORD_FOLLOWUP_PROMPT)
        self.assertIn("<Resolved_Scholarly_Record>", call_kwargs["user_text"])
        self.assertIn("Is working memory domain-general or domain-specific?", call_kwargs["user_text"])

    def test_journal_mode_does_not_reuse_latest_resolved_record(self) -> None:
        session = self.env.create_chat_session(user=self.user, mode=SessionMode.JOURNAL_MATCH)
        with self.env.session() as db:
            chat_service._save_message(
                db=db,
                session_id=session.id,
                role=MessageRole.ASSISTANT,
                content="Prior lookup",
                message_type=MessageType.TEXT,
                tool_results={
                    "type": "academic_lookup",
                    "status": "external_found",
                    "source_mode": "external_scholarly",
                    "confidence": 0.9,
                    "confidence_label": "High",
                    "external_search_used": True,
                    "checked_sources": [],
                    "source_diagnostics": {},
                    "query_terms": ["working", "memory"],
                    "data": {
                        "records": [],
                        "count": 1,
                        "best_record": {
                            "title": "Is working memory domain-general or domain-specific?",
                            "authors": ["Nazbanou Nozari", "Randi C. Martin"],
                            "year": 2024,
                            "venue": "Psychonomic Bulletin & Review",
                            "source": "OpenAlex",
                            "confidence": 0.9,
                            "abstract": "This paper evaluates whether working memory is domain-general.",
                        },
                        "notes": [],
                        "internal_result": {"count": 0, "best_score": 0, "confidence": 0.0},
                    },
                },
            )
            with (
                patch("app.services.chat_service.external_academic_search_service.lookup", side_effect=AssertionError("lookup should not run")),
                patch("app.services.chat_service.ChatService._run_journal_match_from_resolved_record", side_effect=AssertionError("resolved record reuse should not run in explicit journal mode")),
            ):
                response = create_completion(
                    payload=ChatCompletionRequest(session_id=session.id, user_message="Gợi ý tạp chí cho bài này"),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "text")
        self.assertEqual(response.assistant_message.tool_results["type"], "journal_match")
        self.assertEqual(response.assistant_message.tool_results["status"], "insufficient_manuscript_content")


if __name__ == "__main__":
    unittest.main()
