"""
Scientific tools for academic research assistance.

Modules:
- Citation verification   (OpenAlex + Crossref, with PyAlex/Habanero when installed)
- Journal recommendation  (SPECTER2/SciBERT when installed, TF-IDF fallback)
- Retraction scanning     (Crossref update-to + OpenAlex + PubPeer)
- AI writing detection    (RoBERTa ensemble when installed, rule-based fallback)

All heavy ML dependencies (numpy, torch, transformers, sentence-transformers,
pyalex, habanero) are optional and guarded with try/except inside each module.
"""

from app.services.tools.ai_writing_detector import AIWritingDetector, ai_writing_detector
from app.services.tools.citation_checker import CitationChecker, citation_checker
from app.services.tools.journal_finder import JournalFinder, journal_finder
from app.services.tools.retraction_scan import RetractionScanner, retraction_scanner

__all__ = [
    "AIWritingDetector",
    "ai_writing_detector",
    "CitationChecker",
    "citation_checker",
    "JournalFinder",
    "journal_finder",
    "RetractionScanner",
    "retraction_scanner",
]
