"""
Scientific tools for academic research assistance.

Modules:
- Citation verification   (OpenAlex + Crossref, with PyAlex/Habanero when installed)
- Journal recommendation  (SPECTER2 embeddings + ChromaDB semantic search)
- Retraction scanning     (Crossref update-to + OpenAlex + PubPeer)
- AI writing detection    (RoBERTa ensemble when installed, rule-based fallback)

All heavy ML dependencies (numpy, torch, transformers, sentence-transformers,
pyalex, habanero) are optional and guarded with try/except inside each module.
When dependencies or vector data are unavailable, tools degrade to safe
empty/error outputs rather than fabricated fallback data.
"""

from importlib import import_module

_ai_writing_detector_module = import_module("app.services.tools.ai_writing_detector")
_citation_checker_module = import_module("app.services.tools.citation_checker")
_retraction_scan_module = import_module("app.services.tools.retraction_scan")
_grammar_checker_module = import_module("app.services.tools.grammar_checker")

AIWritingDetector = _ai_writing_detector_module.AIWritingDetector
ai_writing_detector_service = _ai_writing_detector_module.ai_writing_detector
CitationChecker = _citation_checker_module.CitationChecker
citation_checker_service = _citation_checker_module.citation_checker
RetractionScanner = _retraction_scan_module.RetractionScanner
retraction_scanner_service = _retraction_scan_module.retraction_scanner
GrammarChecker = _grammar_checker_module.GrammarChecker
grammar_checker_service = _grammar_checker_module.grammar_checker

try:
    _journal_finder_module = import_module("app.services.tools.journal_finder")
    JournalFinder = _journal_finder_module.JournalFinder
    journal_finder_service = _journal_finder_module.journal_finder
except Exception:  # pragma: no cover - optional heavy dependency path
    JournalFinder = None  # type: ignore[assignment]
    journal_finder_service = None  # type: ignore[assignment]

__all__ = [
    "AIWritingDetector",
    "ai_writing_detector_service",
    "CitationChecker",
    "citation_checker_service",
    "JournalFinder",
    "journal_finder_service",
    "RetractionScanner",
    "retraction_scanner_service",
    "GrammarChecker",
    "grammar_checker_service",
]
