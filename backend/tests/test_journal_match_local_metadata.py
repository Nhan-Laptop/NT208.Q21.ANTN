from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.v1.endpoints.chat import create_completion
from app.models.academic_common import VenueType
from app.models.article import Article
from app.models.chat_session import SessionMode
from app.models.entity_fingerprint import EntityFingerprint
from app.models.venue import Venue
from app.models.venue_metric import VenueMetric
from app.models.venue_subject import VenueSubject
from app.schemas.academic import MatchRequestCreate
from app.schemas.chat import ChatCompletionRequest
from app.services.journal_match.service import build_chat_journal_match_payload, journal_match_service
try:
    from .support import TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import TestEnvironment


QUANTUM_PROMPT_VN = """Tiêu đề: Quantum Networks
Tóm tắt: Nghiên cứu về giao thức truyền thông lượng tử và bảo mật mạng.
Từ khóa: quantum, network security
Lĩnh vực: computer science
"""

HEALTH_PROMPT_VN = """Tiêu đề: Health data governance
Tóm tắt: Nghiên cứu về clinical informatics, privacy và hospital data sharing trong bệnh viện.
Từ khóa: clinical informatics, privacy, hospital data sharing
Lĩnh vực: health data governance
"""


class JournalMatchLocalMetadataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()
        self.session = self.env.create_chat_session(user=self.user, mode=SessionMode.JOURNAL_MATCH)
        with self.env.session() as db:
            self._seed_venue(
                db,
                title="Quantum Network Security Journal",
                publisher="Trusted Computing Society",
                homepage_url="https://example.org/quantum-network-security-journal",
                source_url="https://www.scimagojr.com/journalsearch.php?q=21111111111",
                issn_print="1234-5678",
                issn_electronic="8765-4321",
                aims_scope=(
                    "Quantum communication protocols, computer networks, information security, "
                    "cybersecurity, distributed systems, and secure communication."
                ),
                subjects=[
                    "Quantum Communication",
                    "Computer Networks",
                    "Information Security",
                    "Computer Science",
                ],
                citescore=9.2,
                sjr_quartile="Q1",
            )
            self._seed_venue(
                db,
                title="Biomedical Informatics Review",
                publisher="Trusted Health Informatics Association",
                homepage_url="https://example.org/biomedical-informatics-review",
                aims_scope=(
                    "Clinical informatics, biomedical informatics, health data governance, "
                    "medical information systems, privacy, and hospital data sharing."
                ),
                subjects=[
                    "Biomedical Informatics",
                    "Medical Informatics",
                    "Health Informatics",
                    "Health Information Systems",
                ],
                citescore=8.4,
                sjr_quartile="Q1",
            )
            self._seed_venue(
                db,
                title="Digital Health Policy Journal",
                publisher="Health Policy Forum",
                homepage_url="https://example.org/digital-health-policy-journal",
                aims_scope=(
                    "Digital health, health policy, data governance, privacy, and hospital "
                    "information exchange."
                ),
                subjects=[
                    "Digital Health",
                    "Health Policy",
                    "Data Governance",
                    "Health Information Systems",
                ],
                citescore=6.7,
                sjr_quartile="Q2",
            )
            self._seed_venue(
                db,
                title="Computer Science Review Letters",
                publisher="Broad Topics Press",
                homepage_url="https://example.org/computer-science-review-letters",
                aims_scope="General computer science topics across theory, systems, and software.",
                subjects=["Computer Science"],
                citescore=4.3,
                sjr_quartile="Q3",
            )
            db.commit()

    def tearDown(self) -> None:
        self.env.close()

    def _seed_venue(
        self,
        db,
        *,
        title: str,
        publisher: str,
        homepage_url: str | None = None,
        source_url: str | None = None,
        issn_print: str | None = None,
        issn_electronic: str | None = None,
        aims_scope: str,
        subjects: list[str],
        citescore: float,
        sjr_quartile: str,
    ) -> None:
        venue = Venue(
            title=title,
            canonical_title=title,
            venue_type=VenueType.JOURNAL,
            publisher=publisher,
            homepage_url=homepage_url,
            source_url=source_url,
            issn_print=issn_print,
            issn_electronic=issn_electronic,
            aims_scope=aims_scope,
            indexed_scopus=True,
            indexed_wos=True,
            is_open_access=False,
            is_hybrid=True,
        )
        db.add(venue)
        db.flush()
        for label in subjects:
            db.add(VenueSubject(venue_id=venue.id, label=label, source="trusted-index", scheme="keyword"))
        db.add(
            VenueMetric(
                venue_id=venue.id,
                metric_year=2026,
                source_id="trusted-index",
                metric_name="citescore",
                citescore=citescore,
                sjr_quartile=sjr_quartile,
            )
        )
        db.add(
            EntityFingerprint(
                entity_type="venue",
                entity_id=venue.id,
                source_name="trusted-index",
                raw_identifier=venue.canonical_title,
                business_key=f"{publisher.lower().replace(' ', '-')}|{title.lower().replace(' ', '-')}",
            )
        )

    def _run_service_match(self, text: str) -> tuple[dict[str, object], str, dict[str, object], dict[str, object]]:
        with self.env.session() as db:
            request = journal_match_service.create_match_request(
                db,
                current_user=self.user,
                payload=MatchRequestCreate(
                    session_id=self.session.id,
                    text=text,
                    desired_venue_type="journal",
                    top_k=5,
                    include_cfps=False,
                ),
            )
            with patch("app.services.journal_match.service.manuscript_retriever.retrieve", return_value=[]):
                journal_match_service.run_request(db, current_user=self.user, request_id=request.id)
            result = journal_match_service.get_result(db, current_user=self.user, request_id=request.id)
            _matches, summary, payload = build_chat_journal_match_payload(result)
            diagnostics = result["request"].retrieval_diagnostics or {}
            return result, summary, payload, diagnostics

    def test_journal_match_returns_candidates_from_seeded_venue_subjects(self) -> None:
        with self.env.session() as db:
            self.assertEqual(db.query(Article).count(), 0)

        result, _summary, payload, diagnostics = self._run_service_match(
            "Title: Quantum Networks\n"
            "Abstract: A study on quantum communication protocols and network security.\n"
            "Keywords: quantum, network security\n"
            "Subjects: computer science\n"
        )

        self.assertEqual(payload["type"], "journal_match")
        self.assertGreater(len(payload["matches"]), 0)
        self.assertIn("Quantum Network Security Journal", [item["journal"] for item in payload["matches"]])
        self.assertGreater(len(result["candidates"]), 0)
        self.assertEqual(diagnostics["data_sources_used"], ["venues", "venue_subjects", "venue_metrics"])
        self.assertTrue(diagnostics["metadata_only_match"])
        self.assertFalse(diagnostics["insufficient_corpus"])
        self.assertGreater(diagnostics["candidate_count_before_filter"], 0)
        self.assertIn("expanded_subjects", payload["debug"])

    def test_journal_match_includes_trusted_links_when_metadata_exists(self) -> None:
        _result, _summary, payload, _diagnostics = self._run_service_match(
            "Title: Quantum Networks\n"
            "Abstract: A study on quantum communication protocols and network security.\n"
            "Keywords: quantum, network security\n"
            "Subjects: computer science\n"
        )

        quantum_match = next(item for item in payload["matches"] if item["journal"] == "Quantum Network Security Journal")
        self.assertGreater(len(quantum_match["links"]), 0)
        link_types = {link["type"] for link in quantum_match["links"]}
        link_urls = {link["url"] for link in quantum_match["links"]}
        self.assertIn("homepage", link_types)
        self.assertIn("sjr", link_types)
        self.assertIn("issn_portal", link_types)
        self.assertIn("https://example.org/quantum-network-security-journal", link_urls)
        self.assertIn("https://www.scimagojr.com/journalsearch.php?q=21111111111", link_urls)
        self.assertIn("https://portal.issn.org/resource/ISSN/1234-5678", link_urls)

    def test_health_informatics_prompt_matches_related_subjects(self) -> None:
        _result, _summary, payload, diagnostics = self._run_service_match(
            "Title: Health data governance\n"
            "Abstract: Clinical informatics, privacy, and hospital data sharing for healthcare systems.\n"
            "Keywords: clinical informatics, privacy, hospital data sharing\n"
            "Subjects: health data governance\n"
        )

        self.assertEqual(payload["type"], "journal_match")
        self.assertGreater(len(payload["matches"]), 0)
        journals = [item["journal"] for item in payload["matches"]]
        self.assertIn("Biomedical Informatics Review", journals)
        expanded_subjects = payload["debug"]["expanded_subjects"]
        self.assertIn("medical informatics", expanded_subjects)
        self.assertIn("biomedical informatics", expanded_subjects)
        self.assertIn("health informatics", expanded_subjects)
        self.assertEqual(diagnostics["match_status"], "matched")

    def test_quantum_network_security_prompt_matches_computing_security_venues(self) -> None:
        _result, _summary, payload, diagnostics = self._run_service_match(
            "Title: Quantum Networks\n"
            "Abstract: Quantum communication protocols for secure networked systems.\n"
            "Keywords: quantum, network security\n"
            "Subjects: computer science\n"
        )

        self.assertGreater(len(payload["matches"]), 0)
        top_match = payload["matches"][0]
        self.assertEqual(top_match["journal"], "Quantum Network Security Journal")
        expanded_subjects = payload["debug"]["expanded_subjects"]
        self.assertIn("quantum communication", expanded_subjects)
        self.assertIn("computer networks", expanded_subjects)
        self.assertIn("information security", expanded_subjects)
        self.assertEqual(diagnostics["data_sources_used"], ["venues", "venue_subjects", "venue_metrics"])

    def test_specific_subject_matches_outrank_broad_computer_science_match(self) -> None:
        _result, _summary, payload, _diagnostics = self._run_service_match(
            "Title: Quantum Networks\n"
            "Abstract: Quantum communication protocols for secure networked systems.\n"
            "Keywords: quantum, network security\n"
            "Subjects: computer science\n"
        )

        journals = [item["journal"] for item in payload["matches"]]
        self.assertEqual(journals[0], "Quantum Network Security Journal")
        if "Computer Science Review Letters" in journals:
            self.assertLess(
                journals.index("Quantum Network Security Journal"),
                journals.index("Computer Science Review Letters"),
            )

    def test_journal_match_does_not_fabricate_links_when_metadata_missing(self) -> None:
        with self.env.session() as db:
            self._seed_venue(
                db,
                title="Institutional Data Stewardship Notes",
                publisher="Metadata Sparse Press",
                aims_scope="Institutional data stewardship playbooks for hospital governance and records oversight.",
                subjects=["Institutional Data Stewardship", "Hospital Records Governance"],
                citescore=3.1,
                sjr_quartile="Q4",
            )
            db.commit()

        _result, _summary, payload, _diagnostics = self._run_service_match(
            "Title: Institutional Data Stewardship Notes\n"
            "Abstract: Institutional data stewardship guidance for hospital records governance.\n"
            "Keywords: institutional data stewardship, hospital records governance\n"
            "Subjects: institutional data stewardship\n"
        )

        match = next(item for item in payload["matches"] if item["journal"] == "Institutional Data Stewardship Notes")
        self.assertEqual(match["links"], [])
        self.assertTrue(match["link_warning"])

    def test_explicit_journal_mode_does_not_call_external_lookup(self) -> None:
        with (
            patch("app.services.chat_service.external_academic_search_service.lookup", side_effect=AssertionError("external lookup should not run")),
            patch("app.services.chat_service.ChatService._run_journal_match_from_doi", side_effect=AssertionError("DOI routing should not run")),
            patch("app.services.chat_service.ChatService._run_journal_match_from_resolved_record", side_effect=AssertionError("resolved record reuse should not run")),
            patch("app.services.journal_match.service.manuscript_retriever.retrieve", return_value=[]),
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(session_id=self.session.id, user_message=QUANTUM_PROMPT_VN),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "text")
        payload = response.assistant_message.tool_results
        self.assertEqual(payload["type"], "journal_match")
        self.assertGreater(len(payload["matches"]), 0)
        self.assertEqual(payload["source_fields"]["title"], "Quantum Networks")
        self.assertEqual(payload["source_fields"]["field"], "computer science")
        self.assertGreater(len(payload["matches"][0]["links"]), 0)
        content = (response.assistant_message.content or "").lower()
        self.assertNotIn("crossref", content)
        self.assertNotIn("openalex", content)
        self.assertNotIn("không tìm thấy journal phù hợp trong corpus học thuật đã xác minh", content)

    def test_valid_manuscript_with_local_venues_returns_warning_not_insufficient_data(self) -> None:
        _result, summary, payload, diagnostics = self._run_service_match(
            "Title: Health data governance\n"
            "Abstract: Clinical informatics, privacy, and hospital data sharing for healthcare systems.\n"
            "Keywords: clinical informatics, privacy, hospital data sharing\n"
            "Subjects: health data governance\n"
        )

        self.assertEqual(payload["status"], "matched")
        self.assertGreater(len(payload["matches"]), 0)
        self.assertIn(payload["confidence"], {"low", "medium", "high"})
        self.assertIn("warning", payload)
        self.assertFalse(diagnostics["insufficient_corpus"])
        self.assertNotIn("insufficient", summary.lower())
        self.assertIn("venues", payload["debug"]["data_sources_used"])


if __name__ == "__main__":
    unittest.main()
