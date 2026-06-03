"""
Citation Checker — verify references against OpenAlex & Crossref.

Features (auto-selected based on installed packages):
- PyAlex wrapper for OpenAlex             (when ``pyalex`` is installed)
- Habanero wrapper for Crossref / DOI     (when ``habanero`` is installed)
- Direct httpx fallback                   (always available)
- Multi-format extraction: APA, IEEE, Vancouver, DOI, simple author-year
- Fuzzy author matching via difflib
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Any
from difflib import SequenceMatcher

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional deps
# ---------------------------------------------------------------------------
_PYALEX_AVAILABLE = False
try:
    import pyalex
    from pyalex import Works
    pyalex.config.email = "aira@research.local"
    _PYALEX_AVAILABLE = True
except ImportError:
    Works = None  # type: ignore[assignment,misc]

_HABANERO_AVAILABLE = False
try:
    from habanero import Crossref as _HabaneroCrossref
    _HABANERO_AVAILABLE = True
except ImportError:
    _HabaneroCrossref = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Citation patterns
# ---------------------------------------------------------------------------
CITATION_PATTERNS = {
    "apa_inline": re.compile(
        r"([A-Z][a-zA-Z\-']+(?:\s+(?:et\s+al\.?|&\s+[A-Z][a-zA-Z\-']+))?)[,\s]+\(?(\d{4})\)?",
        re.UNICODE,
    ),
    "apa_reference": re.compile(
        r"([A-Z][a-zA-Z\-']+,\s*[A-Z]\.(?:\s*[A-Z]\.)?(?:,?\s*(?:&|and)\s*[A-Z][a-zA-Z\-']+,\s*[A-Z]\.(?:\s*[A-Z]\.)?)*)\s*\((\d{4})\)\.\s*([^.]+\.)",
        re.UNICODE,
    ),
    "ieee": re.compile(
        r'\[(\d+)\]\s*([A-Z]\.\s*[A-Z][a-zA-Z\-\']+(?:,?\s*(?:and\s+)?[A-Z]\.\s*[A-Z][a-zA-Z\-\']+)*)[,\s]+"([^"]+)"',
        re.UNICODE,
    ),
    "vancouver": re.compile(
        r"(\d+)\.\s*([A-Z][a-zA-Z\-']+\s+[A-Z]{1,3}(?:,\s*[A-Z][a-zA-Z\-']+\s+[A-Z]{1,3})*)\.\s*([^.]+)\.",
        re.UNICODE,
    ),
    "doi": re.compile(r"(10\.\d{4,9}/[^\s]+)", re.IGNORECASE),
    "simple": re.compile(r"([A-Z][a-zA-Z\-']+)\s+(?:et\s+al\.?)?\s*\((\d{4})\)"),
}

# Legacy simple regex (kept for backward compat of extract_candidates)
_LEGACY_REGEX = re.compile(r"([A-Z][a-zA-Z\-]+\s+et\s+al\.?[,\s]+\(?\d{4}\)?)")

OPENALEX_SEARCH_URL = "https://api.openalex.org/works"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"
SEMANTIC_SCHOLAR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_FIELDS = (
    "paperId,url,title,authors,year,venue,externalIds,publicationTypes,publicationDate"
)

_REF_SECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"\n\s*references?\s*\n", re.IGNORECASE),
    re.compile(r"\n\s*bibliography\s*\n", re.IGNORECASE),
    re.compile(r"\n\s*tài\s+liệu\s+tham\s+khảo\s*\n", re.IGNORECASE),
]
_NUMBERED_REF_LINE_RE = re.compile(
    r"^\s*(?:\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}[.)])\s+"
)
_DOI_NORMALIZE_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", re.IGNORECASE)
_PMID_URL_RE = re.compile(r"^https?://pubmed\.ncbi\.nlm\.nih\.gov/(\d{4,10})/?$", re.IGNORECASE)
_PMCID_URL_RE = re.compile(
    r"^https?://(?:www\.)?ncbi\.nlm\.nih\.gov/pmc/articles/(PMC\d+)/?$",
    re.IGNORECASE,
)
_OPENALEX_URL_RE = re.compile(
    r"^https?://(?:api\.)?openalex\.org/(?:works/)?(W\d{6,})/?$",
    re.IGNORECASE,
)
_OPENALEX_PREFIX_RE = re.compile(r"^openalex\s*:\s*(W\d{6,})$", re.IGNORECASE)
_OPENALEX_ID_RE = re.compile(r"^W\d{6,}$", re.IGNORECASE)
_EXACT_IDENTIFIER_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "pmid": [
        re.compile(r"https?://pubmed\.ncbi\.nlm\.nih\.gov/\d{4,10}/?", re.IGNORECASE),
        re.compile(r"\bPMID\s*[:=]?\s*\d{4,10}\b", re.IGNORECASE),
    ],
    "pmcid": [
        re.compile(
            r"https?://(?:www\.)?ncbi\.nlm\.nih\.gov/pmc/articles/PMC\d+/?",
            re.IGNORECASE,
        ),
        re.compile(r"\bPMCID\s*[:=]?\s*PMC\d+\b", re.IGNORECASE),
    ],
    "openalex": [
        re.compile(r"https?://(?:api\.)?openalex\.org/(?:works/)?W\d{6,}/?", re.IGNORECASE),
        re.compile(r"\bopenalex\s*:\s*W\d{6,}\b", re.IGNORECASE),
        re.compile(r"\bW\d{6,}\b"),
    ],
}
_IDENTIFIER_DISPLAY_LABELS = {
    "pmid": "PMID",
    "pmcid": "PMCID",
    "openalex": "OpenAlex ID",
}

# ---------------------------------------------------------------------------
# Helpers for citation dedup
# ---------------------------------------------------------------------------


def _inside_doi_block(pos: int, doi_blocks: set[int], block_starts: list[int], blocks: list[str]) -> bool:
    """Return True if *pos* falls inside a block containing an exact identifier."""
    for i in doi_blocks:
        if i < len(block_starts) and i < len(blocks):
            start = block_starts[i]
            end = start + len(blocks[i])
            if start <= pos < end:
                return True
    return False


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class CitationCheckResult:
    """Result of citation verification.

    Status values:
      DOI path:        DOI_VERIFIED | DOI_NOT_FOUND
      Identifier path: IDENTIFIER_VERIFIED | IDENTIFIER_NOT_FOUND
      Metadata path:   METADATA_VERIFIED | LIKELY_MATCH | POSSIBLE_MATCH
                       | AMBIGUOUS_MATCH | UNVERIFIED_NO_DOI | NO_MATCH_FOUND | PARSE_FAILED
      Legacy:          VALID | HALLUCINATED | UNVERIFIED | PARTIAL_MATCH | NO_CITATION_FOUND
    """
    citation: str
    status: str
    evidence: str | None = None
    doi: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    source: str | None = None
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    # No-DOI metadata-matching fields (all optional, backward compatible)
    verification_mode: str | None = None  # "doi" | "identifier_exact" | "metadata_match" | "none"
    input_doi: str | None = None
    matched_doi: str | None = None
    input_identifier: str | None = None
    input_identifier_type: str | None = None
    matched_identifier: str | None = None
    matched_identifier_type: str | None = None
    matched_title: str | None = None
    matched_year: int | None = None
    matched_authors: list[str] = field(default_factory=list)
    matched_venue: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    warning: str | None = None
    evidence_breakdown: dict[str, float] | None = None
    reason: str | None = None
    field_evidence: dict[str, Any] | None = None
    source_diagnostics: dict[str, Any] = field(default_factory=dict)
    parse_status: str | None = None
    search_attempted: bool = False
    search_strategy: str | None = None
    metadata_consistency: str | None = None
    completed_metadata: dict[str, Any] | None = None
    formatted_apa: str | None = None
    formatted_bibtex: str | None = None
    csl_json: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Reference Metadata Parsers and Classes
# ---------------------------------------------------------------------------

@dataclass
class ReferenceMetadata:
    """Parsed reference metadata structure."""
    raw: str
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None
    confidence: float = 0.0


@dataclass
class CandidateWork:
    """Structure representing a candidate matching work retrieved from scholarly APIs."""
    source: str          # e.g., "crossref", "openalex", "semantic_scholar"
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    external_id: str | None = None
    external_id_type: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetadataMatchResult:
    """Detailed matching result for a reference without DOI."""
    reference: ReferenceMetadata
    status: str
    confidence: float
    best_candidate: CandidateWork | None = None
    candidates: list[CandidateWork] = field(default_factory=list)
    candidate_details: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    warning: str | None = None
    reason: str | None = None
    field_evidence: dict[str, Any] | None = None
    source_diagnostics: dict[str, Any] = field(default_factory=dict)
    parse_status: str | None = None
    search_attempted: bool = False
    search_strategy: str | None = None



def normalize_title(title: str) -> str:
    """Normalize paper title for fuzzy matching."""
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r'^[“"‘\'\s\[({]+|[.”"’\'\s\])},;:]+$', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def normalize_author_name(name: str) -> str:
    """Normalize author name to lowercase and strip initials."""
    if not name:
        return ""
    name = name.strip()
    name = re.sub(r'\b(et\s+al\.?|and|&)\b', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[,\.\-\'\"]', ' ', name)
    return name.lower().strip()


def _display_name_part(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.isupper() and len(value) <= 3:
        return value
    return "-".join(part.capitalize() for part in value.split("-") if part)


def normalize_author_for_citation(name: str) -> str:
    """Return a conservative citation-display form without inventing name parts."""
    cleaned = re.sub(r"\s+", " ", (name or "").strip())
    if not cleaned:
        return ""

    cleaned = re.sub(r"\b(et\s+al\.?|and|&)\b", "", cleaned, flags=re.IGNORECASE).strip(" ,;")
    if not cleaned:
        return ""

    if "," in cleaned:
        family, given = [part.strip() for part in cleaned.split(",", 1)]
        family_display = " ".join(_display_name_part(p) for p in family.split() if p)
        initials = []
        for part in re.split(r"[\s.-]+", given):
            if part:
                initials.append(f"{part[0].upper()}.")
        if initials:
            return f"{family_display}, {' '.join(initials)}"
        return family_display

    parts = [p for p in re.split(r"\s+", cleaned) if p]
    if len(parts) == 1:
        return _display_name_part(parts[0])

    family = _display_name_part(parts[-1])
    initials = [f"{part[0].upper()}." for part in parts[:-1] if part]
    if initials:
        return f"{family}, {' '.join(initials)}"
    return family


def _format_apa_authors(authors: list[str]) -> str:
    formatted = [normalize_author_for_citation(a) for a in authors if a]
    formatted = [a for a in formatted if a]
    if not formatted:
        return ""
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} & {formatted[1]}"
    return f"{', '.join(formatted[:-1])}, & {formatted[-1]}"


def infer_item_type(metadata: dict[str, Any]) -> str:
    """Infer a BibTeX-safe item type from source metadata."""
    raw_type = str(metadata.get("raw_type") or metadata.get("type") or "").lower()
    venue = str(metadata.get("venue") or "").lower()
    publication_types = metadata.get("publication_types") or []
    if isinstance(publication_types, str):
        publication_types = [publication_types]
    publication_type_text = " ".join(str(p).lower() for p in publication_types)

    combined = f"{raw_type} {venue} {publication_type_text}"
    if any(token in combined for token in ("proceeding", "conference", "symposium", "workshop")):
        return "inproceedings"
    if any(token in combined for token in ("journal", "article")):
        return "article"
    if metadata.get("volume") or metadata.get("issue"):
        return "article"
    return "misc"


def build_completed_metadata(
    candidate: CandidateWork,
    confidence: float,
    source: str | None = None,
) -> dict[str, Any]:
    """Build source-backed completion metadata from the selected candidate only."""
    if not candidate:
        return {}

    raw = candidate.raw or {}
    publication_types = raw.get("publicationTypes")
    metadata: dict[str, Any] = {}
    for key, value in (
        ("source", source or candidate.source),
        ("confidence", round(confidence, 3)),
        ("title", candidate.title),
        ("authors", list(candidate.authors or [])),
        ("year", candidate.year),
        ("venue", candidate.venue),
        ("doi", candidate.doi),
        ("url", candidate.url),
        ("external_id", candidate.external_id),
        ("external_id_type", candidate.external_id_type),
        ("volume", candidate.volume),
        ("issue", candidate.issue),
        ("pages", candidate.pages),
        ("publication_types", publication_types),
        ("raw_type", raw.get("type")),
    ):
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        metadata[key] = value

    item_type = infer_item_type(metadata)
    metadata["type"] = item_type
    metadata.pop("raw_type", None)
    if metadata.get("publication_types") is None:
        metadata.pop("publication_types", None)
    return metadata


def _append_sentence_period(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value[-1] in ".!?":
        return value
    return f"{value}."


def format_apa_reference(metadata: dict[str, Any]) -> str:
    """Format an APA-like reference from source-backed metadata."""
    if not metadata:
        return ""

    authors = metadata.get("authors") or []
    if not isinstance(authors, list):
        authors = []
    author_text = _format_apa_authors([str(a) for a in authors])
    year = metadata.get("year")
    year_text = f"({year})." if year else "(n.d.)."
    title = str(metadata.get("title") or "").strip()
    venue = str(metadata.get("venue") or "").strip()
    volume = str(metadata.get("volume") or "").strip()
    issue = str(metadata.get("issue") or "").strip()
    pages = str(metadata.get("pages") or "").strip()
    doi = str(metadata.get("doi") or "").strip()
    url = str(metadata.get("url") or "").strip()

    parts: list[str] = []
    if author_text:
        parts.append(_append_sentence_period(author_text))
        parts.append(year_text)
        if title:
            parts.append(_append_sentence_period(title))
    else:
        if title:
            parts.append(_append_sentence_period(title))
        parts.append(year_text)

    container = ""
    if venue:
        container = venue
        if volume:
            container += f", {volume}"
            if issue:
                container += f"({issue})"
        elif issue:
            container += f", ({issue})"
        if pages:
            container += f", {pages}"
    elif pages:
        container = pages
    if container:
        parts.append(_append_sentence_period(container))

    if doi:
        parts.append(f"https://doi.org/{doi}")
    elif url:
        parts.append(url)

    return " ".join(part for part in parts if part).strip()


def _bibtex_escape(value: str) -> str:
    return (
        (value or "")
        .replace("\\", "\\textbackslash{}")
        .replace("{", "\\{")
        .replace("}", "\\}")
    )


def _bibtex_key(metadata: dict[str, Any]) -> str:
    authors = metadata.get("authors") or []
    first_author = ""
    if isinstance(authors, list) and authors:
        first_author = normalize_author_name(str(authors[0])).split()[-1]

    title = normalize_title(str(metadata.get("title") or ""))
    title_words = [
        word for word in re.findall(r"[a-z0-9]+", title)
        if word not in {"a", "an", "the", "and", "of", "in", "on", "for", "to"}
    ]
    seed = first_author or (title_words[0] if title_words else "ref")
    year = str(metadata.get("year") or "nd")
    suffix = "".join(title_words[:3]) or "work"
    key = re.sub(r"[^A-Za-z0-9]+", "", f"{seed}{year}{suffix}")
    return key or "refndwork"


def format_bibtex(metadata: dict[str, Any]) -> str:
    """Format deterministic BibTeX without inventing DOI/URL or missing fields."""
    if not metadata:
        return ""

    item_type = infer_item_type(metadata)
    key = _bibtex_key(metadata)
    fields: list[tuple[str, Any]] = []

    def add(name: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        fields.append((name, value))

    add("title", metadata.get("title"))
    authors = metadata.get("authors") or []
    if isinstance(authors, list) and authors:
        author_text = " and ".join(normalize_author_for_citation(str(a)) for a in authors if a)
        add("author", author_text)
    add("year", metadata.get("year"))
    venue_field = "booktitle" if item_type == "inproceedings" else "journal"
    add(venue_field, metadata.get("venue"))
    add("volume", metadata.get("volume"))
    add("number", metadata.get("issue"))
    add("pages", metadata.get("pages"))
    add("doi", metadata.get("doi"))
    add("url", metadata.get("url"))

    body = "\n".join(
        f"  {name} = {{{_bibtex_escape(str(value))}}},"
        for name, value in fields
    )
    if body:
        return f"@{item_type}{{{key},\n{body}\n}}"
    return f"@{item_type}{{{key}\n}}"


def _csl_author(name: str) -> dict[str, str]:
    formatted = normalize_author_for_citation(name)
    if "," in formatted:
        family, given = [part.strip() for part in formatted.split(",", 1)]
        author = {"family": family}
        if given:
            author["given"] = given
        return author
    return {"family": formatted} if formatted else {}


def build_csl_json(metadata: dict[str, Any]) -> dict[str, Any]:
    """Build compact CSL JSON from source-backed metadata."""
    if not metadata:
        return {}

    item_type = infer_item_type(metadata)
    csl_type = {
        "article": "article-journal",
        "inproceedings": "paper-conference",
        "misc": "article",
    }.get(item_type, "article")
    csl: dict[str, Any] = {"type": csl_type}

    for src_key, dst_key in (
        ("title", "title"),
        ("venue", "container-title"),
        ("volume", "volume"),
        ("issue", "issue"),
        ("pages", "page"),
        ("doi", "DOI"),
        ("url", "URL"),
        ("external_id", "id"),
    ):
        value = metadata.get(src_key)
        if value is not None and (not isinstance(value, str) or value.strip()):
            csl[dst_key] = value

    authors = metadata.get("authors") or []
    if isinstance(authors, list) and authors:
        csl_authors = [_csl_author(str(a)) for a in authors]
        csl_authors = [a for a in csl_authors if a]
        if csl_authors:
            csl["author"] = csl_authors

    year = metadata.get("year")
    if year:
        csl["issued"] = {"date-parts": [[year]]}

    return csl


def normalize_venue(venue: str) -> str:
    """Normalize venue/journal name for matching."""
    if not venue:
        return ""
    v = venue.strip()
    v = re.sub(r'^[“"‘\'\s\[({]+|[.”"’\'\s\])},;:]+$', '', v)
    v = re.sub(r'^(the\s+)?journal\s+of\s+', '', v, flags=re.IGNORECASE)
    v = re.sub(r'^(the\s+)?proceedings\s+of\s+', '', v, flags=re.IGNORECASE)
    v = re.sub(r'\s+', ' ', v).strip().lower()
    return v


_MATCH_WEIGHTS = {
    "title": 0.45,
    "authors": 0.25,
    "year": 0.15,
    "venue": 0.10,
    "volume_issue_pages": 0.05,
}
_SOURCE_ERROR_STATES = {"timeout", "http_error", "error"}
_TITLE_MATCH_THRESHOLD = 0.75
_TITLE_STRONG_THRESHOLD = 0.90
_AUTHOR_MATCH_THRESHOLD = 0.80
_AUTHOR_PARTIAL_THRESHOLD = 0.50
_VENUE_MATCH_THRESHOLD = 0.80
_VENUE_PARTIAL_THRESHOLD = 0.50
_LOW_PARSE_CONFIDENCE = 0.40


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


def _empty_source_diagnostic(state: str = "skipped", detail: str | None = None) -> dict[str, Any]:
    return {
        "state": state,
        "candidate_count": 0,
        "detail": detail,
    }


def _classify_source_exception(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", "Request timed out."
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code is not None:
            return "http_error", f"HTTP {status_code}"
        return "http_error", "HTTP error."
    if isinstance(exc, httpx.RequestError):
        return "error", str(exc)
    return "error", str(exc)


def _candidate_missing_fields(ref: ReferenceMetadata, candidate: CandidateWork) -> list[str]:
    missing: list[str] = []
    if ref.authors and not candidate.authors:
        missing.append("authors")
    if ref.year is not None and candidate.year is None:
        missing.append("year")
    if ref.venue and not candidate.venue:
        missing.append("venue")
    if (ref.volume or ref.issue or ref.pages) and not (candidate.volume or candidate.issue or candidate.pages):
        missing.append("volume_issue_pages")
    if not candidate.doi:
        missing.append("doi")
    return missing


def _join_reasons(parts: list[str]) -> str | None:
    cleaned = [part.strip() for part in parts if part and part.strip()]
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def _build_match_reason(
    status: str,
    field_evidence: dict[str, Any] | None,
    *,
    source_diagnostics: dict[str, Any] | None = None,
    parse_status: str | None = None,
    metadata_consistency: str | None = None,
    exact_label: str | None = None,
) -> str:
    if status == "PARSE_FAILED":
        return "Could not extract enough structured or title-like metadata to search scholarly sources."

    if status == "UNVERIFIED":
        degraded = [
            f"{source}: {diag.get('state')}"
            for source, diag in (source_diagnostics or {}).items()
            if isinstance(diag, dict) and diag.get("state") in _SOURCE_ERROR_STATES
        ]
        detail = f" Sources degraded: {', '.join(degraded)}." if degraded else ""
        return f"Could not verify this reference because scholarly source lookups were degraded.{detail}"

    if status == "NO_MATCH_FOUND":
        if parse_status == "LOW_CONFIDENCE_FALLBACK_USED":
            return "Low-confidence parsing triggered a fallback search, but no scholarly source produced a plausible candidate."
        return "No scholarly source produced a plausible metadata candidate for this reference."

    if exact_label:
        prefix = f"{exact_label} resolved exactly to a scholarly record."
        if metadata_consistency == "not_provided":
            return prefix
        if metadata_consistency == "consistent":
            return f"{prefix} The supplied metadata matches the resolved record."
        if metadata_consistency == "partial_mismatch":
            return f"{prefix} Some supplied metadata matches, but other fields differ from the resolved record."
        if metadata_consistency == "mismatch":
            return f"{prefix} The supplied metadata conflicts with the resolved record."
        return prefix

    evidence = field_evidence or {}
    positive: list[str] = []
    caution: list[str] = []
    title_ev = evidence.get("title") or {}
    title_verdict = title_ev.get("verdict")
    if title_verdict == "match":
        positive.append("title matches strongly")
    elif title_verdict == "partial_match":
        caution.append("title is only partially similar")
    elif title_verdict == "mismatch":
        caution.append("title differs")

    author_ev = evidence.get("authors") or {}
    author_verdict = author_ev.get("verdict")
    if author_verdict == "match":
        positive.append("authors align well")
    elif author_verdict == "partial_match":
        positive.append("authors partially align")
    elif author_verdict == "mismatch":
        caution.append("authors differ")

    year_ev = evidence.get("year") or {}
    year_verdict = year_ev.get("verdict")
    if year_verdict == "exact":
        positive.append("year matches exactly")
    elif year_verdict == "near_match":
        positive.append("year is close")
    elif year_verdict == "mismatch":
        caution.append("year differs")

    venue_ev = evidence.get("venue") or {}
    venue_verdict = venue_ev.get("verdict")
    if venue_verdict == "match":
        positive.append("venue matches")
    elif venue_verdict == "partial_match":
        positive.append("venue is partially aligned")
    elif venue_verdict == "mismatch":
        caution.append("venue differs")

    vol_ev = evidence.get("volume_issue_pages") or {}
    vol_verdict = vol_ev.get("verdict")
    if vol_verdict == "exact":
        positive.append("volume/pages align")
    elif vol_verdict == "partial_match":
        positive.append("volume/pages partially align")
    elif vol_verdict == "mismatch":
        caution.append("volume/pages differ")

    pieces: list[str] = []
    positive_text = _join_reasons(positive)
    caution_text = _join_reasons(caution)
    if positive_text:
        pieces.append(positive_text[:1].upper() + positive_text[1:] + ".")
    if caution_text:
        pieces.append(caution_text[:1].upper() + caution_text[1:] + ".")

    if not pieces:
        if status == "AMBIGUOUS_MATCH":
            return "Multiple candidates scored similarly, so the match remains ambiguous."
        if status == "UNVERIFIED_NO_DOI":
            return "A candidate exists, but the supporting metadata is too weak to verify this reference."
        return "Metadata evidence was evaluated against scholarly candidates."

    if status == "AMBIGUOUS_MATCH":
        pieces.append("Multiple candidates scored too closely to auto-select one confidently.")
    elif status == "POSSIBLE_MATCH":
        pieces.append("The evidence is limited, so this remains only a possible match.")
    elif status == "LIKELY_MATCH":
        pieces.append("The evidence supports a likely match, but not a verified one.")
    elif status == "METADATA_VERIFIED":
        pieces.append("The combined evidence is strong enough to verify this metadata match.")
    elif status == "UNVERIFIED_NO_DOI":
        pieces.append("The candidate evidence is too weak to verify the match.")
    return " ".join(pieces)


def _build_fallback_title_query(raw: str, parsed: ReferenceMetadata) -> str | None:
    if parsed.title:
        significant_words = re.findall(r"[A-Za-z]{4,}", parsed.title)
        if len(significant_words) >= 4:
            return parsed.title.strip()

    cleaned = raw or ""
    cleaned = CITATION_PATTERNS["doi"].sub(" ", cleaned)
    for patterns in _EXACT_IDENTIFIER_PATTERNS.values():
        for pattern in patterns:
            cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"\b(19\d{2}|20[0-2]\d)\b", " ", cleaned)
    cleaned = re.sub(r"[^A-Za-z\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None

    tokens = [tok for tok in cleaned.split() if len(tok) >= 4]
    if len(tokens) < 4:
        return None
    return " ".join(tokens[:18]).strip()


def _compare_reference_to_candidate(
    ref: ReferenceMetadata,
    candidate: CandidateWork,
) -> dict[str, Any]:
    title_similarity = None
    title_verdict = "not_provided"
    if ref.title:
        if candidate.title:
            ref_title_norm = normalize_title(ref.title)
            cand_title_norm = normalize_title(candidate.title)
            title_similarity = SequenceMatcher(None, ref_title_norm, cand_title_norm).ratio()
            if title_similarity >= _TITLE_STRONG_THRESHOLD:
                title_verdict = "match"
            elif title_similarity >= _TITLE_MATCH_THRESHOLD:
                title_verdict = "partial_match"
            else:
                title_verdict = "mismatch"
        else:
            title_verdict = "missing_candidate"

    author_overlap = None
    author_verdict = "not_provided"
    ref_authors_norm = [normalize_author_name(a) for a in ref.authors if a]
    cand_authors_norm = [normalize_author_name(a) for a in candidate.authors if a]
    if ref_authors_norm:
        if cand_authors_norm:
            matches = 0
            for ref_author in ref_authors_norm:
                if any(
                    ref_author == cand_author
                    or ref_author in cand_author.split()
                    or cand_author in ref_author.split()
                    or SequenceMatcher(None, ref_author, cand_author).ratio() > 0.85
                    for cand_author in cand_authors_norm
                ):
                    matches += 1
            author_overlap = matches / len(ref_authors_norm)
            if author_overlap >= _AUTHOR_MATCH_THRESHOLD:
                author_verdict = "match"
            elif author_overlap >= _AUTHOR_PARTIAL_THRESHOLD:
                author_verdict = "partial_match"
            else:
                author_verdict = "mismatch"
        else:
            author_verdict = "missing_candidate"

    year_score = None
    year_verdict = "not_provided"
    if ref.year is not None:
        if candidate.year is not None:
            diff = abs(ref.year - candidate.year)
            if diff == 0:
                year_score = 1.0
                year_verdict = "exact"
            elif diff == 1:
                year_score = 0.5
                year_verdict = "near_match"
            else:
                year_score = 0.0
                year_verdict = "mismatch"
        else:
            year_verdict = "missing_candidate"

    venue_similarity = None
    venue_verdict = "not_provided"
    if ref.venue:
        if candidate.venue:
            ref_venue_norm = normalize_venue(ref.venue)
            cand_venue_norm = normalize_venue(candidate.venue)
            venue_similarity = SequenceMatcher(None, ref_venue_norm, cand_venue_norm).ratio()
            if venue_similarity >= _VENUE_MATCH_THRESHOLD:
                venue_verdict = "match"
            elif venue_similarity >= _VENUE_PARTIAL_THRESHOLD:
                venue_verdict = "partial_match"
            else:
                venue_verdict = "mismatch"
        else:
            venue_verdict = "missing_candidate"

    volume_matches = 0
    volume_comparable = 0
    if ref.volume and candidate.volume:
        volume_comparable += 1
        if ref.volume.strip() == candidate.volume.strip():
            volume_matches += 1
    if ref.issue and candidate.issue:
        volume_comparable += 1
        if ref.issue.strip() == candidate.issue.strip():
            volume_matches += 1
    if ref.pages and candidate.pages:
        volume_comparable += 1
        if ref.pages.strip().replace("–", "-") == candidate.pages.strip().replace("–", "-"):
            volume_matches += 1
    volume_issue_pages_score = None
    volume_issue_pages_verdict = "not_provided"
    if ref.volume or ref.issue or ref.pages:
        if volume_comparable > 0:
            volume_issue_pages_score = volume_matches / volume_comparable
            if volume_issue_pages_score == 1.0:
                volume_issue_pages_verdict = "exact"
            elif volume_issue_pages_score > 0.0:
                volume_issue_pages_verdict = "partial_match"
            else:
                volume_issue_pages_verdict = "mismatch"
        else:
            volume_issue_pages_verdict = "missing_candidate"

    field_evidence = {
        "title": {
            "input": ref.title,
            "candidate": candidate.title,
            "similarity": _safe_float(title_similarity),
            "verdict": title_verdict,
        },
        "authors": {
            "input": list(ref.authors or []),
            "candidate": list(candidate.authors or []),
            "similarity": _safe_float(author_overlap),
            "verdict": author_verdict,
        },
        "year": {
            "input": ref.year,
            "candidate": candidate.year,
            "similarity": _safe_float(year_score),
            "verdict": year_verdict,
        },
        "venue": {
            "input": ref.venue,
            "candidate": candidate.venue,
            "similarity": _safe_float(venue_similarity),
            "verdict": venue_verdict,
        },
        "volume_issue_pages": {
            "input": {
                "volume": ref.volume,
                "issue": ref.issue,
                "pages": ref.pages,
            },
            "candidate": {
                "volume": candidate.volume,
                "issue": candidate.issue,
                "pages": candidate.pages,
            },
            "similarity": _safe_float(volume_issue_pages_score),
            "verdict": volume_issue_pages_verdict,
        },
        "doi": {
            "input": ref.doi,
            "candidate": candidate.doi,
            "similarity": None,
            "verdict": "exact" if ref.doi and candidate.doi and ref.doi == candidate.doi else (
                "source_backed" if candidate.doi else "missing_candidate"
            ),
        },
    }

    available_weight = 0.0
    weighted_score = 0.0
    corroborating_comparable = 0
    corroborating_strong = 0

    for field_name, similarity in (
        ("title", title_similarity),
        ("authors", author_overlap),
        ("year", year_score),
        ("venue", venue_similarity),
        ("volume_issue_pages", volume_issue_pages_score),
    ):
        if similarity is None:
            continue
        weight = _MATCH_WEIGHTS[field_name]
        available_weight += weight
        weighted_score += weight * similarity
        if field_name != "title":
            corroborating_comparable += 1
            if similarity >= 0.5:
                corroborating_strong += 1

    final_score = (weighted_score / available_weight) if available_weight > 0 else 0.0
    missing_fields = _candidate_missing_fields(ref, candidate)

    return {
        "title_similarity": round(title_similarity or 0.0, 3),
        "author_overlap": round(author_overlap or 0.0, 3),
        "year_score": round(year_score or 0.0, 3),
        "venue_similarity": round(venue_similarity or 0.0, 3),
        "page_volume_bonus": round(volume_issue_pages_score or 0.0, 3),
        "final_score": round(final_score, 3),
        "available_weight": round(available_weight, 3),
        "weighted_score": round(weighted_score, 3),
        "corroborating_comparable": corroborating_comparable,
        "corroborating_strong": corroborating_strong,
        "field_evidence": field_evidence,
        "candidate_missing_fields": missing_fields,
    }


def _candidate_has_incomplete_metadata(ref: ReferenceMetadata, candidate: CandidateWork) -> bool:
    missing = _candidate_missing_fields(ref, candidate)
    critical_missing = {"authors", "year"}
    return any(field in critical_missing for field in missing) or len(missing) >= 3


def _top_source_candidate(candidates: list[CandidateWork], source: str) -> CandidateWork | None:
    for candidate in candidates:
        if candidate.source == source:
            return candidate
    return None


def _has_source_conflict(ref: ReferenceMetadata, candidates: list[CandidateWork]) -> bool:
    crossref_candidate = _top_source_candidate(candidates, "crossref")
    openalex_candidate = _top_source_candidate(candidates, "openalex")
    if not crossref_candidate or not openalex_candidate:
        return False
    if crossref_candidate.title and openalex_candidate.title:
        if normalize_title(crossref_candidate.title) != normalize_title(openalex_candidate.title):
            return False
    if ref.year is not None and crossref_candidate.year and openalex_candidate.year:
        if crossref_candidate.year != openalex_candidate.year:
            return True
    if ref.venue and crossref_candidate.venue and openalex_candidate.venue:
        if normalize_venue(crossref_candidate.venue) != normalize_venue(openalex_candidate.venue):
            return True
    return False


def _metadata_consistency_from_field_evidence(field_evidence: dict[str, Any] | None) -> str:
    evidence = field_evidence or {}
    comparable_verdicts: list[str] = []
    for field_name in ("title", "authors", "year", "venue", "volume_issue_pages"):
        field = evidence.get(field_name) or {}
        input_value = field.get("input")
        if input_value in (None, "", [], {}):
            continue
        verdict = field.get("verdict")
        if verdict in {"not_provided", "missing_candidate"}:
            continue
        if verdict:
            comparable_verdicts.append(str(verdict))
    if not comparable_verdicts:
        return "not_provided"
    if all(verdict in {"match", "exact"} for verdict in comparable_verdicts):
        return "consistent"
    if any(verdict == "mismatch" for verdict in comparable_verdicts):
        if any(verdict in {"match", "exact", "partial_match", "near_match"} for verdict in comparable_verdicts):
            return "partial_mismatch"
        return "mismatch"
    if any(verdict in {"partial_match", "near_match"} for verdict in comparable_verdicts):
        return "partial_mismatch"
    return "consistent"


def extract_authors(author_part: str) -> list[str]:
    """Helper to extract normalized author names from author string."""
    if not author_part:
        return []
    
    author_part = re.sub(r'^\s*(?:\[\d+\]|\d+\.?)\s*', '', author_part)
    author_part = re.sub(r'\b(et\s+al\.?)\b.*', '', author_part, flags=re.IGNORECASE)
    
    # 1. Try to find LastName, Initials pattern (APA reference)
    apa_matches = re.findall(r"([A-Z][a-zA-Z\-']+),\s*[A-Z]\.", author_part)
    if apa_matches:
        return [normalize_author_name(name) for name in apa_matches if name.strip()]
        
    # 2. Try to find Initials LastName pattern (IEEE)
    ieee_matches = re.findall(r"(?:[A-Z]\.\s*)+([A-Z][a-zA-Z\-']+)", author_part)
    if ieee_matches:
        return [normalize_author_name(name) for name in ieee_matches if name.strip()]
        
    # 3. Fallback: split by comma / & / and
    parts = re.split(r',|\b(?:and|&)\b', author_part)
    results = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        p_clean = re.sub(r'\b(?:[A-Z]\b\.?\s*)+', '', p)
        p_clean = re.sub(r'\b[A-Z]{1,2}\b', '', p_clean)
        p_clean = p_clean.strip()
        words = p_clean.split()
        if words:
            results.append(normalize_author_name(words[-1]))
        else:
            orig_words = p.split()
            if orig_words:
                results.append(normalize_author_name(orig_words[-1]))
    return [r for r in results if r]


def parse_reference_metadata(raw: str) -> ReferenceMetadata:
    """Parse raw reference string into structured ReferenceMetadata without using LLM."""
    raw_clean = (raw or "").strip()
    raw_clean = re.sub(r'\s+', ' ', raw_clean)
    
    # 1. Extract DOI
    doi = None
    doi_match = CITATION_PATTERNS["doi"].search(raw_clean)
    if doi_match:
        doi = CitationChecker.normalize_doi(doi_match.group(1))
        
    # 2. Extract Year
    year = None
    years = [int(y) for y in re.findall(r'\b(19\d{2}|20[0-2]\d)\b', raw_clean)]
    parentheses_year_match = re.search(r'\(\s*(19\d{2}|20[0-2]\d)\s*\)', raw_clean)
    if parentheses_year_match:
        year = int(parentheses_year_match.group(1))
    elif years:
        year = years[-1]
        
    title = None
    authors = []
    venue = None
    volume = None
    issue = None
    pages = None
    
    # Extract Volume, Issue, Pages bằng các regex chung trước
    vol_issue_match = re.search(r'\b(\d+)\((\d+)\)', raw_clean)
    if vol_issue_match:
        volume = vol_issue_match.group(1)
        issue = vol_issue_match.group(2)
    else:
        vol_match = re.search(r'\b(?:vol\.|volume)\s*(\d+)\b', raw_clean, re.IGNORECASE)
        if vol_match:
            volume = vol_match.group(1)
        issue_match = re.search(r'\b(?:no\.|number|issue)\s*(\d+)\b', raw_clean, re.IGNORECASE)
        if issue_match:
            issue = issue_match.group(1)
            
    pages_match = re.search(r'\bpp\.\s*([a-zA-Z0-9]+[-–][a-zA-Z0-9]+|[a-zA-Z0-9]+)\b', raw_clean, re.IGNORECASE)
    if not pages_match:
        pages_match = re.search(r'\bpages\s*([a-zA-Z0-9]+[-–][a-zA-Z0-9]+|[a-zA-Z0-9]+)\b', raw_clean, re.IGNORECASE)
    if not pages_match:
        pages_match = re.search(r'\b([0-9]+[-–][0-9]+)\b', raw_clean)
    if pages_match:
        pages = pages_match.group(1)

    # 3. Parse Title, Authors, Venue based on formats
    quotes_match = re.search(r'["“]([^"”]+)["”]', raw_clean)
    
    if quotes_match:
        # IEEE-like
        title = quotes_match.group(1).strip()
        idx = raw_clean.find(quotes_match.group(0))
        author_part = raw_clean[:idx].strip()
        authors = extract_authors(author_part)
        
        rest = raw_clean[idx + len(quotes_match.group(0)):].strip()
        rest_parts = [p.strip() for p in rest.split(',') if p.strip()]
        venue_candidates = []
        for p in rest_parts:
            if not any(word in p.lower() for word in ['vol.', 'volume', 'no.', 'number', 'issue', 'pp.', 'pages']) and not re.search(r'\b(19\d{2}|20\d{2})\b', p):
                venue_candidates.append(p)
        if venue_candidates:
            venue = venue_candidates[0].strip()
            
    elif parentheses_year_match:
        # APA-like
        idx_start = parentheses_year_match.start()
        idx_end = parentheses_year_match.end()
        author_part = raw_clean[:idx_start].strip()
        authors = extract_authors(author_part)
        
        rest = raw_clean[idx_end:].strip()
        rest = re.sub(r'^[.\s,;:–\-]+', '', rest)
        rest_sentences = [s.strip() for s in rest.split('. ') if s.strip()]
        if rest_sentences:
            title = rest_sentences[0].strip()
            if len(rest_sentences) > 1:
                v_cand = rest_sentences[1].strip()
                venue = re.split(r',|\bvol\b|\bvolume\b', v_cand, flags=re.IGNORECASE)[0].strip()
                
                # Cố gắng trích xuất volume/issue/pages bổ sung từ v_cand nếu chưa có
                if not volume or not issue or not pages:
                    vi_m = re.search(r'\b(\d+)\((\d+)\)', v_cand)
                    if vi_m:
                        if not volume:
                            volume = vi_m.group(1)
                        if not issue:
                            issue = vi_m.group(2)
                    
                    if not pages:
                        p_m = re.search(r'\b(?:pp\.|pages)\s*([a-zA-Z0-9]+[-–][a-zA-Z0-9]+|[a-zA-Z0-9]+)\b', v_cand, re.IGNORECASE)
                        if not p_m:
                            p_m = re.search(r'\b([0-9]+[-–][0-9]+)\b', v_cand)
                        if p_m:
                            pages = p_m.group(1)
                            
                    if not volume and venue:
                        temp = v_cand[len(venue):].strip()
                        if pages:
                            temp = temp.replace(pages, "")
                        vol_cand_match = re.search(r'\b(\d+)\b', temp)
                        if vol_cand_match:
                            volume = vol_cand_match.group(1)
                            
    else:
        # Plain reference / Fallback / Vancouver-like
        cleaned_raw = re.sub(r'^\s*(?:\[\d+\]|\d+\.?)\s*', '', raw_clean)
        parts = re.split(r'(?<=\.)\s+(?=[A-Z][a-zA-Z]{1,})', cleaned_raw)
        if len(parts) >= 3:
            authors = extract_authors(parts[0])
            title = parts[1].strip()
            venue_cand = parts[2].strip()
            venue = re.split(r',|\bvol\b|\bvolume\b', venue_cand, flags=re.IGNORECASE)[0].strip()
            
            # Trích xuất bổ sung từ venue_cand nếu chưa có
            if not volume or not issue or not pages:
                vi_m = re.search(r'\b(\d+)\((\d+)\)', venue_cand)
                if vi_m:
                    if not volume:
                        volume = vi_m.group(1)
                    if not issue:
                        issue = vi_m.group(2)
                if not pages:
                    p_m = re.search(r'\b(?:pp\.|pages)\s*([a-zA-Z0-9]+[-–][a-zA-Z0-9]+|[a-zA-Z0-9]+)\b', venue_cand, re.IGNORECASE)
                    if not p_m:
                        p_m = re.search(r'\b([0-9]+[-–][0-9]+)\b', venue_cand)
                    if p_m:
                        pages = p_m.group(1)
                if not volume and venue:
                    temp = venue_cand[len(venue):].strip()
                    if pages:
                        temp = temp.replace(pages, "")
                    vol_cand_match = re.search(r'\b(\d+)\b', temp)
                    if vol_cand_match:
                        volume = vol_cand_match.group(1)
        elif len(parts) == 2:
            authors = extract_authors(parts[0])
            title = parts[1].strip()
        else:
            title = cleaned_raw

    # 4. Clean-up title & venue (strip punctuation marks)
    if title:
        title = re.sub(r'^[“"‘\'\s\[({,]+|[.”"’\'\s\])},;:]+$', '', title).strip()
    if venue:
        venue = re.sub(r'^[“"‘\'\s\[({,]+|[.”"’\'\s\])},;:]+$', '', venue).strip()

    # 5. Calculate parse confidence
    confidence = 0.05
    if not title:
        if authors and year:
            confidence = 0.35
        elif year:
            confidence = 0.20
    else:
        if year:
            if authors:
                confidence = 0.85
            else:
                confidence = 0.65
        else:
            if authors:
                confidence = 0.50
            else:
                confidence = 0.30

    return ReferenceMetadata(
        raw=raw,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        volume=volume,
        issue=issue,
        pages=pages,
        doi=doi,
        confidence=confidence
    )


def _normalize_crossref_work(item: dict[str, Any]) -> CandidateWork:
    """Normalize a Crossref API work item into CandidateWork."""
    if not item:
        return CandidateWork(source="crossref")

    # 1. Title
    title = None
    titles = item.get("title")
    if titles and isinstance(titles, list) and len(titles) > 0:
        title = titles[0]
    elif isinstance(titles, str):
        title = titles

    # 2. Authors
    authors = []
    author_list = item.get("author", [])
    if isinstance(author_list, list):
        for a in author_list:
            if not isinstance(a, dict):
                continue
            family = a.get("family", "").strip()
            given = a.get("given", "").strip()
            if family:
                authors.append(normalize_author_name(family))
            elif given:
                authors.append(normalize_author_name(given))

    # 3. Year
    year = None
    for key in ("published-print", "published-online", "published", "issued"):
        pub = item.get(key)
        if pub and isinstance(pub, dict) and "date-parts" in pub:
            parts = pub["date-parts"]
            if parts and isinstance(parts, list) and len(parts) > 0 and len(parts[0]) > 0:
                try:
                    year = int(parts[0][0])
                    break
                except (ValueError, TypeError):
                    pass

    # 4. Venue/Container Title
    venue = None
    containers = item.get("container-title")
    if containers and isinstance(containers, list) and len(containers) > 0:
        venue = containers[0]
    elif isinstance(containers, str):
        venue = containers

    # 5. DOI
    doi = item.get("DOI")
    if doi:
        doi = CitationChecker.normalize_doi(doi)

    # 6. URL / IDs / Volume / Issue / Pages
    url = item.get("URL") if isinstance(item.get("URL"), str) else None
    volume = item.get("volume")
    issue = item.get("issue")
    pages = item.get("page")

    return CandidateWork(
        source="crossref",
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        url=url,
        external_id=doi,
        external_id_type="crossref" if doi else None,
        volume=volume,
        issue=issue,
        pages=pages,
        raw=item
    )


def search_crossref_candidates(ref: ReferenceMetadata, limit: int = 5) -> list[CandidateWork]:
    """Search Crossref for candidate matching works based on reference metadata without crashing."""
    if not ref:
        return []

    # Xây dựng câu query
    query_parts = []
    if ref.title:
        query_parts.append(ref.title)
    if ref.authors:
        query_parts.append(ref.authors[0])
    if ref.venue:
        query_parts.append(ref.venue)
    if ref.year:
        query_parts.append(str(ref.year))
        
    query = " ".join(query_parts).strip()
    if not query:
        return []

    candidates: list[CandidateWork] = []

    # 1. Thử dùng Habanero nếu có sẵn
    if _HABANERO_AVAILABLE:
        try:
            cr = _HabaneroCrossref()
            res = cr.works(query=query, limit=limit)
            if res and isinstance(res, dict) and "message" in res and "items" in res["message"]:
                items = res["message"]["items"]
                for item in items:
                    candidate = _normalize_crossref_work(item)
                    if candidate:
                        candidates.append(candidate)
                if candidates:
                    return candidates
        except Exception as e:
            logger.warning("Crossref candidate search via Habanero failed: %s. Falling back to HTTP.", e)

    # 2. HTTP Fallback dùng httpx
    try:
        url = CROSSREF_WORKS_URL
        params = {
            "query": query,
            "rows": limit
        }
        headers = {
            "User-Agent": "AIRA/1.0 (mailto:aira@research.local)"
        }
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code == 200:
                items = resp.json().get("message", {}).get("items", [])
                for item in items:
                    candidate = _normalize_crossref_work(item)
                    if candidate:
                        candidates.append(candidate)
            else:
                logger.warning("Crossref HTTP query returned status code %s", resp.status_code)
    except Exception as e:
        logger.warning("Crossref candidate search via HTTP fallback failed: %s", e)

    return candidates


def _normalize_openalex_work(item: dict[str, Any]) -> CandidateWork:
    """Normalize an OpenAlex work item into CandidateWork."""
    if not item:
        return CandidateWork(source="openalex")

    title = item.get("display_name") or item.get("title")

    authors: list[str] = []
    for a in item.get("authorships", []) or []:
        if not isinstance(a, dict):
            continue
        author = a.get("author") or {}
        name = author.get("display_name") if isinstance(author, dict) else None
        if name:
            authors.append(normalize_author_name(name))

    year = item.get("publication_year")
    if year is not None:
        try:
            year = int(year)
        except (ValueError, TypeError):
            year = None

    venue = None
    primary = item.get("primary_location") or {}
    if isinstance(primary, dict):
        source = primary.get("source") or {}
        if isinstance(source, dict):
            venue = source.get("display_name")
    if not venue:
        host_venue = item.get("host_venue") or {}
        if isinstance(host_venue, dict):
            venue = host_venue.get("display_name")

    doi = item.get("doi")
    if doi:
        doi = CitationChecker.normalize_doi(doi)

    url = None
    primary = item.get("primary_location") or {}
    if isinstance(primary, dict):
        url = primary.get("landing_page_url") or primary.get("pdf_url")
    if not url:
        url = item.get("id") if isinstance(item.get("id"), str) else None

    biblio = item.get("biblio") or {}
    volume = biblio.get("volume") if isinstance(biblio, dict) else None
    issue = biblio.get("issue") if isinstance(biblio, dict) else None
    first_page = biblio.get("first_page") if isinstance(biblio, dict) else None
    last_page = biblio.get("last_page") if isinstance(biblio, dict) else None
    pages = None
    if first_page and last_page:
        pages = f"{first_page}-{last_page}"
    elif first_page:
        pages = str(first_page)

    return CandidateWork(
        source="openalex",
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        url=url,
        external_id=item.get("id") if isinstance(item.get("id"), str) else None,
        external_id_type="openalex" if item.get("id") else None,
        volume=str(volume) if volume is not None else None,
        issue=str(issue) if issue is not None else None,
        pages=pages,
        raw=item,
    )


def search_openalex_candidates(ref: ReferenceMetadata, limit: int = 5) -> list[CandidateWork]:
    """Search OpenAlex for candidate matching works based on reference metadata.

    Mirrors search_crossref_candidates: never crashes; returns [] on any failure.
    """
    if not ref or not ref.title:
        return []

    query = ref.title.strip()
    if not query:
        return []

    candidates: list[CandidateWork] = []

    # 1. Try pyalex wrapper if available
    if _PYALEX_AVAILABLE and Works is not None:
        try:
            works_iter = Works().search(query).get(per_page=limit)
            for item in works_iter or []:
                if isinstance(item, dict):
                    cand = _normalize_openalex_work(item)
                    if cand:
                        candidates.append(cand)
            if candidates:
                return candidates
        except Exception as e:
            logger.warning("OpenAlex candidate search via pyalex failed: %s. Falling back to HTTP.", e)

    # 2. HTTP fallback
    try:
        params = {"search": query, "per_page": limit}
        headers = {"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(OPENALEX_SEARCH_URL, params=params, headers=headers)
            if resp.status_code == 200:
                items = resp.json().get("results", [])
                for item in items:
                    cand = _normalize_openalex_work(item)
                    if cand:
                        candidates.append(cand)
            else:
                logger.warning("OpenAlex HTTP query returned status code %s", resp.status_code)
    except Exception as e:
        logger.warning("OpenAlex candidate search via HTTP fallback failed: %s", e)

    return candidates


def _normalize_semantic_scholar_paper(paper: dict[str, Any]) -> CandidateWork | None:
    """Normalize a Semantic Scholar Graph API paper into CandidateWork."""
    if not isinstance(paper, dict):
        return None

    title = paper.get("title")
    if not isinstance(title, str) or not title.strip():
        return None

    authors: list[str] = []
    for author in paper.get("authors", []) or []:
        if not isinstance(author, dict):
            continue
        name = author.get("name")
        if isinstance(name, str) and name.strip():
            authors.append(name.strip())

    year = paper.get("year")
    if year is not None:
        try:
            year = int(year)
        except (TypeError, ValueError):
            year = None

    venue = paper.get("venue")
    if not isinstance(venue, str) or not venue.strip():
        venue = None

    external_ids = paper.get("externalIds") or {}
    doi = None
    if isinstance(external_ids, dict):
        doi_value = external_ids.get("DOI")
        if isinstance(doi_value, str) and doi_value.strip():
            doi = CitationChecker.normalize_doi(doi_value)

    paper_id = paper.get("paperId")
    if paper_id is not None:
        paper_id = str(paper_id)

    url = paper.get("url")
    if not isinstance(url, str) or not url.strip():
        url = None

    return CandidateWork(
        source="semantic_scholar",
        title=title.strip(),
        authors=authors,
        year=year,
        venue=venue.strip() if isinstance(venue, str) else None,
        doi=doi,
        url=url,
        external_id=paper_id,
        external_id_type="semantic_scholar" if paper_id else None,
        raw=paper,
    )


def search_semantic_scholar_candidates(ref: ReferenceMetadata, limit: int = 5) -> list[CandidateWork]:
    """Search Semantic Scholar for candidate matching works; return [] on all failures."""
    if not ref or not ref.title:
        return []

    settings = get_settings()
    if not settings.semantic_scholar_enabled:
        return []

    query = ref.title.strip()
    if not query:
        return []

    headers = {"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key

    params = {
        "query": query,
        "limit": max(1, min(limit, 10)),
        "fields": SEMANTIC_SCHOLAR_FIELDS,
    }

    candidates: list[CandidateWork] = []
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(SEMANTIC_SCHOLAR_SEARCH_URL, params=params, headers=headers)
        if resp.status_code == 429 or resp.status_code >= 500:
            logger.warning("Semantic Scholar query returned retryable status code %s", resp.status_code)
            return []
        if resp.status_code != 200:
            logger.warning("Semantic Scholar query returned status code %s", resp.status_code)
            return []
        payload = resp.json()
        papers = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(papers, list):
            return []
        for paper in papers:
            candidate = _normalize_semantic_scholar_paper(paper)
            if candidate:
                candidates.append(candidate)
    except (httpx.TimeoutException, httpx.RequestError, ValueError, TypeError) as e:
        logger.warning("Semantic Scholar candidate search failed: %s", e)
        return []
    except Exception as e:
        logger.warning("Semantic Scholar candidate search failed unexpectedly: %s", e)
        return []

    return candidates


def _merge_candidates(*candidate_groups: list[CandidateWork]) -> list[CandidateWork]:
    """Merge candidates from scholarly sources, deduping by DOI, external ID, then title+year."""
    merged: list[CandidateWork] = []
    seen_dois: set[str] = set()
    seen_external_ids: set[tuple[str, str]] = set()
    seen_title_year: set[tuple[str, int | None]] = set()

    def _add(cand: CandidateWork) -> None:
        if cand.doi:
            key = cand.doi.lower()
            if key in seen_dois:
                return
            seen_dois.add(key)
        if cand.external_id:
            external_key = ((cand.external_id_type or cand.source).lower(), cand.external_id.lower())
            if external_key in seen_external_ids:
                return
            seen_external_ids.add(external_key)
        if cand.title:
            tkey = normalize_title(cand.title)
            title_year_key = (tkey, cand.year)
            if tkey and title_year_key in seen_title_year:
                return
            if tkey:
                seen_title_year.add(title_year_key)
        merged.append(cand)

    for group in candidate_groups:
        for c in group:
            _add(c)
    return merged


def score_candidate(ref: ReferenceMetadata, candidate: CandidateWork) -> dict[str, Any]:
    """Calculate similarity scores and final matching score between reference and candidate work."""
    return _compare_reference_to_candidate(ref, candidate)


def choose_best_match(ref: ReferenceMetadata, candidates: list[CandidateWork]) -> MetadataMatchResult:
    """Evaluate and select the best candidate match, assigning matching status based on safety rules."""
    if not ref or ref.confidence <= _LOW_PARSE_CONFIDENCE or not ref.title:
        return MetadataMatchResult(
            reference=ref,
            status="PARSE_FAILED",
            confidence=0.0,
            warning="Parsing failed or title is missing in reference metadata.",
            reason="Could not extract enough structured or title-like metadata to search scholarly sources.",
            parse_status="UNPARSABLE",
        )

    if not candidates:
        warning = None
        if not ref.doi:
            warning = "Warning: Citation does not contain DOI, matched via metadata search."
        return MetadataMatchResult(
            reference=ref,
            status="NO_MATCH_FOUND",
            confidence=0.0,
            warning=warning,
            reason="No scholarly source produced a plausible metadata candidate for this reference.",
        )

    # Calculate scores for all candidates and sort them
    scored_candidates = []
    for cand in candidates:
        evidence = score_candidate(ref, cand)
        scored_candidates.append((cand, evidence))

    # Sort by final_score descending
    scored_candidates.sort(key=lambda x: x[1]["final_score"], reverse=True)

    # Top candidates to store (up to 3)
    top_3 = [item[0] for item in scored_candidates[:3]]
    top_3_details = [
        {
            "source": item[0].source,
            "title": item[0].title,
            "authors": list(item[0].authors or []),
            "year": item[0].year,
            "venue": item[0].venue,
            "doi": item[0].doi,
            "url": item[0].url,
            "external_id": item[0].external_id,
            "external_id_type": item[0].external_id_type,
            "score": item[1]["final_score"],
            "missing_fields": list(item[1].get("candidate_missing_fields") or []),
        }
        for item in scored_candidates[:3]
    ]
    best_cand, best_evidence = scored_candidates[0]
    top1_score = best_evidence["final_score"]

    # Basic Verdict Assignment
    status = "UNVERIFIED_NO_DOI"
    if top1_score >= 0.90:
        status = "METADATA_VERIFIED"
    elif top1_score >= 0.80:
        status = "LIKELY_MATCH"
    elif top1_score >= 0.65:
        status = "POSSIBLE_MATCH"
    else:
        status = "UNVERIFIED_NO_DOI"

    title_similarity = best_evidence.get("title_similarity", 0.0)
    title_verdict = ((best_evidence.get("field_evidence") or {}).get("title") or {}).get("verdict")

    # Safety caps
    if title_similarity < _TITLE_MATCH_THRESHOLD or title_verdict == "mismatch":
        if status in ("METADATA_VERIFIED", "LIKELY_MATCH"):
            status = "POSSIBLE_MATCH"

    comparable_support = int(best_evidence.get("corroborating_comparable", 0))
    corroborating_support = int(best_evidence.get("corroborating_strong", 0))
    if comparable_support == 0 and status in {"METADATA_VERIFIED", "LIKELY_MATCH"}:
        status = "POSSIBLE_MATCH"
    elif corroborating_support == 0 and status in {"METADATA_VERIFIED", "LIKELY_MATCH"}:
        status = "POSSIBLE_MATCH"
    elif comparable_support == 1 and status == "METADATA_VERIFIED":
        status = "LIKELY_MATCH"

    if not (ref.authors and ref.year is not None) and status == "METADATA_VERIFIED":
        status = "LIKELY_MATCH"

    # Ambiguity check: top1_score - top2_score < 0.05 and top1_score >= 0.65
    if len(scored_candidates) > 1 and top1_score >= 0.65:
        top2_score = scored_candidates[1][1]["final_score"]
        if (top1_score - top2_score) < 0.05:
            status = "AMBIGUOUS_MATCH"

    # Set warnings if input does not have DOI
    warning = None
    if not ref.doi:
        warning = "Warning: Citation does not contain DOI, matched via metadata search."
    if status in {"LIKELY_MATCH", "POSSIBLE_MATCH", "AMBIGUOUS_MATCH", "UNVERIFIED_NO_DOI"}:
        warning = (
            "Candidate found, but confidence is not high enough to generate a verified formatted citation."
        )

    return MetadataMatchResult(
        reference=ref,
        status=status,
        confidence=top1_score,
        best_candidate=best_cand,
        candidates=top_3,
        candidate_details=top_3_details,
        evidence=best_evidence,
        warning=warning,
        reason=_build_match_reason(status, best_evidence.get("field_evidence")),
        field_evidence=best_evidence.get("field_evidence"),
    )


# ---------------------------------------------------------------------------
# CitationChecker
# ---------------------------------------------------------------------------

class CitationChecker:
    """Verify citations using OpenAlex + Crossref with graceful fallback."""

    def __init__(self) -> None:
        self._crossref = _HabaneroCrossref() if _HABANERO_AVAILABLE else None
        self._http_client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._http_client is None:
            transport = httpx.HTTPTransport(retries=2)
            self._http_client = httpx.Client(timeout=10.0, transport=transport)
        return self._http_client

    def close(self) -> None:
        """Cleanly close the HTTP client."""
        if self._http_client:
            self._http_client.close()
            self._http_client = None

    @staticmethod
    def _normalize_input_text(text: str) -> str:
        normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        # Keep newlines for section/reference splitting; normalize inline spacing.
        normalized = re.sub(r"[\t\f\v ]+", " ", normalized)
        return normalized

    @staticmethod
    def _normalize_doi(raw: str) -> str:
        doi = (raw or "").strip()
        doi = _DOI_NORMALIZE_RE.sub("", doi)
        doi = doi.strip(" \t\n\r<>{}[]\"'")
        doi = doi.rstrip(".,;:")
        # Drop trailing unmatched ')' captured from noisy text.
        while doi.endswith(")") and doi.count("(") < doi.count(")"):
            doi = doi[:-1]
        return doi.lower()

    @classmethod
    def normalize_doi(cls, raw: str) -> str:
        return cls._normalize_doi(raw)

    @classmethod
    def normalize_exact_identifier(cls, raw: str, identifier_type: str) -> str | None:
        value = (raw or "").strip()
        if not value:
            return None

        normalized_type = (identifier_type or "").strip().lower()
        if normalized_type == "pmid":
            url_match = _PMID_URL_RE.match(value)
            if url_match:
                return url_match.group(1)
            inline = re.search(r"(\d{4,10})", value)
            return inline.group(1) if inline else None

        if normalized_type == "pmcid":
            url_match = _PMCID_URL_RE.match(value)
            if url_match:
                return url_match.group(1).upper()
            inline = re.search(r"(PMC\d+)", value, re.IGNORECASE)
            return inline.group(1).upper() if inline else None

        if normalized_type == "openalex":
            url_match = _OPENALEX_URL_RE.match(value)
            if url_match:
                return url_match.group(1).upper()
            prefix_match = _OPENALEX_PREFIX_RE.match(value)
            if prefix_match:
                return prefix_match.group(1).upper()
            if _OPENALEX_ID_RE.match(value):
                return value.upper()
            inline = re.search(r"\b(W\d{6,})\b", value, re.IGNORECASE)
            return inline.group(1).upper() if inline else None

        return None

    @staticmethod
    def _identifier_lookup_value(identifier: str, identifier_type: str) -> str:
        normalized_type = (identifier_type or "").lower()
        if normalized_type in {"pmid", "pmcid"}:
            return f"{normalized_type}:{identifier}"
        return identifier

    @classmethod
    def _extract_identifier_from_openalex_work(
        cls,
        work: dict[str, Any],
        identifier_type: str,
    ) -> str | None:
        ids = work.get("ids") or {}
        if not isinstance(ids, dict):
            ids = {}

        normalized_type = (identifier_type or "").lower()
        raw_value: str | None = None
        if normalized_type == "openalex":
            for candidate in (work.get("id"), ids.get("openalex")):
                if isinstance(candidate, str) and candidate.strip():
                    raw_value = candidate
                    break
        else:
            candidate = ids.get(normalized_type)
            if isinstance(candidate, str) and candidate.strip():
                raw_value = candidate

        if not raw_value:
            return None
        return cls.normalize_exact_identifier(raw_value, normalized_type)

    @staticmethod
    def _source_diagnostics_for_exact(
        *,
        source: str | None,
        verification_mode: str,
        resolved: bool,
    ) -> dict[str, Any]:
        if verification_mode == "doi":
            diagnostics = {
                "crossref": _empty_source_diagnostic("skipped"),
                "openalex": _empty_source_diagnostic("skipped"),
            }
            if resolved:
                if source and "crossref" in source:
                    diagnostics["crossref"] = _empty_source_diagnostic("matched")
                    diagnostics["crossref"]["candidate_count"] = 1
                elif source and "openalex" in source:
                    diagnostics["crossref"] = _empty_source_diagnostic("no_match")
                    diagnostics["openalex"] = _empty_source_diagnostic("matched")
                    diagnostics["openalex"]["candidate_count"] = 1
            else:
                diagnostics["crossref"] = _empty_source_diagnostic("no_match")
                diagnostics["openalex"] = _empty_source_diagnostic("no_match")
            return diagnostics

        diagnostics = {
            "openalex": _empty_source_diagnostic("matched" if resolved else "no_match"),
        }
        if resolved:
            diagnostics["openalex"]["candidate_count"] = 1
        return diagnostics

    @staticmethod
    def _reference_has_user_metadata(ref: ReferenceMetadata | None) -> bool:
        if ref is None:
            return False
        return bool(
            ref.title
            or ref.authors
            or ref.year is not None
            or ref.venue
            or ref.volume
            or ref.issue
            or ref.pages
        )

    def _reference_from_exact_context(self, citation_context: dict[str, Any] | None) -> ReferenceMetadata | None:
        if not citation_context:
            return None
        raw_reference = _safe_text(citation_context.get("raw") or citation_context.get("context_block"))
        if not raw_reference:
            return None
        ref = parse_reference_metadata(raw_reference)
        if not self._reference_has_user_metadata(ref):
            return None
        if not (
            ref.authors
            or ref.year is not None
            or ref.venue
            or ref.volume
            or ref.issue
            or ref.pages
        ):
            title_like_query = _build_fallback_title_query(raw_reference, ref)
            if not title_like_query:
                return None
        return ref

    @staticmethod
    def _candidate_from_exact_result(result: CitationCheckResult) -> CandidateWork:
        metadata = result.metadata or {}
        if isinstance(metadata.get("crossref"), dict):
            return _normalize_crossref_work(metadata["crossref"])
        if isinstance(metadata.get("openalex"), dict):
            return _normalize_openalex_work(metadata["openalex"])
        return CandidateWork(
            source=result.source or "exact",
            title=result.title,
            authors=list(result.authors or []),
            year=result.year,
            venue=result.matched_venue,
            doi=result.doi,
        )

    def _annotate_exact_result(
        self,
        result: CitationCheckResult,
        *,
        citation_context: dict[str, Any] | None,
        exact_label: str,
        exact_value: str | None,
        verification_mode: str,
    ) -> CitationCheckResult:
        candidate = self._candidate_from_exact_result(result)
        result.matched_doi = result.matched_doi or candidate.doi
        result.matched_title = result.matched_title or candidate.title
        result.matched_year = result.matched_year if result.matched_year is not None else candidate.year
        result.matched_authors = list(result.matched_authors or candidate.authors or [])
        result.matched_venue = result.matched_venue or candidate.venue
        completed_metadata = build_completed_metadata(candidate, result.confidence or 1.0, source=result.source)
        result.completed_metadata = completed_metadata or None
        result.formatted_apa = format_apa_reference(completed_metadata) or None if completed_metadata else None
        result.formatted_bibtex = format_bibtex(completed_metadata) or None if completed_metadata else None
        result.csl_json = build_csl_json(completed_metadata) or None if completed_metadata else None
        result.source_diagnostics = self._source_diagnostics_for_exact(
            source=result.source,
            verification_mode=verification_mode,
            resolved=result.status in {"DOI_VERIFIED", "IDENTIFIER_VERIFIED"},
        )
        result.search_attempted = True
        result.search_strategy = "exact_lookup"
        result.parse_status = "NOT_PROVIDED"

        ref = self._reference_from_exact_context(citation_context)
        if ref is not None:
            comparison = _compare_reference_to_candidate(ref, candidate)
            field_evidence = comparison.get("field_evidence") or {}
            result.field_evidence = field_evidence
            result.metadata_consistency = _metadata_consistency_from_field_evidence(field_evidence)
            result.parse_status = "HIGH_CONFIDENCE" if ref.confidence > _LOW_PARSE_CONFIDENCE else "LOW_CONFIDENCE"
        else:
            result.field_evidence = {}
            result.metadata_consistency = "not_provided"

        if verification_mode == "doi":
            result.field_evidence["doi"] = {
                "input": exact_value,
                "candidate": result.doi,
                "similarity": None,
                "verdict": "exact" if result.doi else "missing_candidate",
            }
        else:
            result.field_evidence["exact_identifier"] = {
                "input": exact_value,
                "candidate": result.matched_identifier or exact_value,
                "similarity": None,
                "verdict": "exact" if result.status == "IDENTIFIER_VERIFIED" else "missing_candidate",
            }

        result.reason = _build_match_reason(
            result.status,
            result.field_evidence,
            source_diagnostics=result.source_diagnostics,
            metadata_consistency=result.metadata_consistency,
            exact_label=exact_label,
        )
        if result.metadata_consistency in {"partial_mismatch", "mismatch"}:
            result.warning = (
                f"{exact_label} is valid, but the supplied metadata differs from the resolved scholarly record."
            )
        return result

    def extract_dois(self, text: str) -> list[str]:
        normalized_text = self._normalize_input_text(text)
        dois: set[str] = set()
        for match in CITATION_PATTERNS["doi"].finditer(normalized_text):
            doi = self._normalize_doi(match.group(1))
            if doi:
                dois.add(doi)
        return sorted(dois)

    def extract_exact_identifiers(self, text: str) -> list[dict[str, str]]:
        normalized_text = self._normalize_input_text(text)
        extracted: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        for identifier_type, patterns in _EXACT_IDENTIFIER_PATTERNS.items():
            for pattern in patterns:
                for match in pattern.finditer(normalized_text):
                    raw = match.group(0).strip()
                    normalized = self.normalize_exact_identifier(raw, identifier_type)
                    if not normalized:
                        continue
                    key = (identifier_type, normalized.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    extracted.append(
                        {
                            "raw": raw,
                            "identifier": normalized,
                            "identifier_type": identifier_type,
                        }
                    )

        extracted.sort(key=lambda item: normalized_text.find(item["raw"]))
        return extracted

    @staticmethod
    def _extract_references_section(text: str) -> str | None:
        if not text:
            return None
        for pat in _REF_SECTION_PATTERNS:
            m = pat.search(text)
            if not m:
                continue
            section = text[m.end():].strip()
            if len(section) >= 40:
                return section
        return None

    @staticmethod
    def _split_reference_blocks(text: str) -> list[str]:
        if not text:
            return []

        lines = [ln.rstrip() for ln in text.split("\n")]
        blocks: list[str] = []
        current: list[str] = []

        def _flush() -> None:
            if not current:
                return
            block = " ".join(part.strip() for part in current if part.strip())
            block = re.sub(r"\s+", " ", block).strip()
            if len(block) >= 20:
                blocks.append(block)
            current.clear()

        for line in lines:
            stripped = line.strip()
            if not stripped:
                _flush()
                continue

            if _NUMBERED_REF_LINE_RE.match(stripped) and current:
                _flush()

            cleaned = _NUMBERED_REF_LINE_RE.sub("", stripped)
            current.append(cleaned)

        _flush()

        # Fallback: if numbering split failed, keep dense non-empty lines.
        if not blocks:
            for ln in lines:
                ln = re.sub(r"\s+", " ", ln).strip()
                if len(ln) >= 20:
                    blocks.append(ln)

        # De-duplicate while preserving order.
        deduped: list[str] = []
        seen: set[str] = set()
        for block in blocks:
            key = block.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(block)
        return deduped

    # -- extraction --------------------------------------------------------

    def extract_candidates(self, text: str) -> list[str]:
        """Legacy helper used by the endpoint (returns raw strings)."""
        return sorted({m.strip() for m in _LEGACY_REGEX.findall(text)})

    def extract_citations(self, text: str) -> list[dict[str, Any]]:
        """Extract citations using multiple format patterns."""
        normalized_text = self._normalize_input_text(text)
        citations: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _add_citation(item: dict[str, Any], key: str) -> None:
            if key in seen:
                return
            seen.add(key)
            citations.append(item)

        segments: list[str] = [normalized_text]
        ref_section = self._extract_references_section(normalized_text)
        if ref_section:
            segments.append(ref_section)

        blocks: list[str] = []
        for segment in segments:
            blocks.extend(self._split_reference_blocks(segment))

        # Track each block's character position in normalized_text.
        block_starts: list[int] = []
        for blk in blocks:
            pos = normalized_text.find(blk, block_starts[-1] if block_starts else 0)
            block_starts.append(pos if pos >= 0 else 0)

        # Identify blocks that contain an exact identifier.
        doi_blocks: set[int] = set()
        for i, blk in enumerate(blocks):
            if CITATION_PATTERNS["doi"].search(blk) or self.extract_exact_identifiers(blk):
                doi_blocks.add(i)

        # Exact identifier extraction from structured blocks first so the full
        # citation context is preserved for metadata-consistency comparison.
        for block in blocks:
            for identifier in self.extract_exact_identifiers(block):
                identifier_type = identifier["identifier_type"]
                normalized = identifier["identifier"]
                _add_citation(
                    {
                        "raw": block,
                        "exact_raw": identifier["raw"],
                        "type": identifier_type,
                        "identifier": normalized,
                        "identifier_type": identifier_type,
                        "doi": None,
                        "authors": None,
                        "year": None,
                        "context_block": block,
                    },
                    key=f"{identifier_type}:{normalized.lower()}",
                )

        # Exact identifier extraction from whole text as a fallback.
        for segment in [normalized_text]:
            for identifier in self.extract_exact_identifiers(segment):
                identifier_type = identifier["identifier_type"]
                normalized = identifier["identifier"]
                _add_citation(
                    {
                        "raw": identifier["raw"],
                        "exact_raw": identifier["raw"],
                        "type": identifier_type,
                        "identifier": normalized,
                        "identifier_type": identifier_type,
                        "doi": None,
                        "authors": None,
                        "year": None,
                        "context_block": None,
                    },
                    key=f"{identifier_type}:{normalized.lower()}",
                )

        # DOI extraction from blocks first so metadata around the DOI is kept.
        for block in blocks:
            for doi_m in CITATION_PATTERNS["doi"].finditer(block):
                doi = self._normalize_doi(doi_m.group(1))
                if not doi:
                    continue
                _add_citation(
                    {
                        "raw": block,
                        "exact_raw": doi_m.group(1),
                        "type": "doi",
                        "doi": doi,
                        "authors": None,
                        "year": None,
                        "context_block": block,
                    },
                    key=f"doi:{doi.lower()}",
                )

        # DOI extraction from whole text as a fallback.
        for segment in [normalized_text]:
            for doi_m in CITATION_PATTERNS["doi"].finditer(segment):
                doi = self._normalize_doi(doi_m.group(1))
                if not doi:
                    continue
                _add_citation(
                    {
                        "raw": doi,
                        "exact_raw": doi_m.group(1),
                        "type": "doi",
                        "doi": doi,
                        "authors": None,
                        "year": None,
                        "context_block": None,
                    },
                    key=f"doi:{doi.lower()}",
                )

        # Structured extraction from blocks (multiline references, numbered lists).
        # Skip blocks that already have an exact identifier — the exact entry is authoritative
        # and any partial regex match from the same block is a fragment.
        for i, block in enumerate(blocks):
            if i in doi_blocks:
                continue

            for match in CITATION_PATTERNS["apa_reference"].finditer(block):
                authors_raw = match.group(1).strip()
                year = match.group(2)
                title_part = match.group(3).strip()
                first_author = authors_raw.split(",", 1)[0].strip()
                _add_citation(
                    {
                        "raw": f"{authors_raw} ({year}). {title_part}",
                        "type": "apa_reference",
                        "authors": [first_author] if first_author else None,
                        "year": int(year),
                        "doi": None,
                    },
                    key=f"apa_ref:{authors_raw.lower()}:{year}:{title_part.lower()[:60]}",
                )

            for match in CITATION_PATTERNS["ieee"].finditer(block):
                idx = match.group(1)
                author_blob = match.group(2).strip()
                title_blob = match.group(3).strip()
                first_author = author_blob.split()[-1] if author_blob else ""
                _add_citation(
                    {
                        "raw": block,
                        "type": "ieee",
                        "authors": [first_author] if first_author else None,
                        "year": None,
                        "doi": None,
                    },
                    key=f"ieee:{idx}:{title_blob.lower()[:80]}",
                )

            for match in CITATION_PATTERNS["vancouver"].finditer(block):
                idx = match.group(1)
                author_blob = match.group(2).strip()
                title_blob = match.group(3).strip()
                first_author = author_blob.split()[0] if author_blob else ""
                _add_citation(
                    {
                        "raw": block,
                        "type": "vancouver",
                        "authors": [first_author] if first_author else None,
                        "year": None,
                        "doi": None,
                    },
                    key=f"vancouver:{idx}:{title_blob.lower()[:80]}",
                )

        # Inline extraction from full text (author-year forms).
        # Skip matches that fall within a block already claimed by an exact identifier.
        for match in CITATION_PATTERNS["apa_inline"].finditer(normalized_text):
            if _inside_doi_block(match.start(), doi_blocks, block_starts, blocks):
                continue
            author, year = match.group(1).strip(), match.group(2)
            _add_citation(
                {
                    "raw": match.group(0),
                    "type": "apa_inline",
                    "authors": [author],
                    "year": int(year),
                    "doi": None,
                },
                key=f"apa_inline:{author.lower()}:{year}",
            )

        for match in CITATION_PATTERNS["simple"].finditer(normalized_text):
            if _inside_doi_block(match.start(), doi_blocks, block_starts, blocks):
                continue
            author, year = match.group(1).strip(), match.group(2)
            _add_citation(
                {
                    "raw": match.group(0),
                    "type": "simple",
                    "authors": [author],
                    "year": int(year),
                    "doi": None,
                },
                key=f"simple:{author.lower()}:{year}",
            )

        return citations

    # -- DOI verification --------------------------------------------------

    def _verify_doi_crossref(self, doi: str) -> CitationCheckResult | None:
        doi = self._normalize_doi(doi)
        if self._crossref is not None:
            try:
                result = self._crossref.works(ids=doi)
                if result and "message" in result:
                    msg = result["message"]
                    resolved_doi = self._normalize_doi(str(msg.get("DOI") or doi))
                    if resolved_doi != doi:
                        logger.debug("Crossref returned non-exact DOI %s for %s", resolved_doi, doi)
                        return None
                    title = msg.get("title", [""])[0]
                    authors = [f"{a.get('family', '')} {a.get('given', '')}".strip() for a in msg.get("author", [])]
                    year = None
                    for key in ("published-print", "published-online"):
                        if key in msg:
                            year = msg[key]["date-parts"][0][0]
                            break
                    return CitationCheckResult(
                        citation=doi, status="DOI_VERIFIED",
                        evidence=f"Verified via Crossref: {title}",
                        doi=resolved_doi, title=title, authors=authors, year=year,
                        source="crossref", confidence=1.0, metadata={"crossref": msg},
                    )
            except Exception as e:
                logger.debug("Crossref lookup failed for %s: %s", doi, e)

        # HTTP fallback
        try:
            resp = self._get_client().get(f"{CROSSREF_WORKS_URL}/{doi}")
            if resp.status_code == 200:
                data = resp.json().get("message", {})
                resolved_doi = self._normalize_doi(str(data.get("DOI") or doi))
                if resolved_doi != doi:
                    logger.debug("Crossref HTTP returned non-exact DOI %s for %s", resolved_doi, doi)
                    return None
                title = data.get("title", [""])[0]
                return CitationCheckResult(
                    citation=doi, status="DOI_VERIFIED",
                    evidence=f"Verified via Crossref HTTP: {title}",
                    doi=resolved_doi, title=title, source="crossref_http", confidence=0.95,
                    metadata={"crossref": data},
                )
        except Exception as e:
            logger.debug("Crossref HTTP failed for %s: %s", doi, e)
        return None

    def _verify_doi_openalex_exact(self, doi: str) -> CitationCheckResult | None:
        doi = self._normalize_doi(doi)
        filter_values = (doi, f"https://doi.org/{doi}")
        for value in filter_values:
            try:
                resp = self._get_client().get(
                    OPENALEX_SEARCH_URL,
                    params={"filter": f"doi:{value}", "per-page": 1},
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
                if not results:
                    continue
                top = results[0]
                resolved_doi = self._normalize_doi(str(top.get("doi") or doi))
                if resolved_doi != doi:
                    logger.debug("OpenAlex returned non-exact DOI %s for %s", resolved_doi, doi)
                    continue
                return CitationCheckResult(
                    citation=doi,
                    status="DOI_VERIFIED",
                    evidence=f"Verified via OpenAlex DOI lookup: {top.get('display_name')}",
                    doi=resolved_doi,
                    title=top.get("display_name"),
                    year=top.get("publication_year"),
                    source="openalex_doi",
                    confidence=0.9,
                    metadata={"openalex": top},
                )
            except Exception as e:
                logger.debug("OpenAlex exact DOI lookup failed for %s: %s", doi, e)
        return None

    def verify_doi_exact(
        self,
        raw_doi: str,
        citation_context: dict[str, Any] | None = None,
    ) -> CitationCheckResult:
        doi = self._normalize_doi(raw_doi)
        if not doi:
            return CitationCheckResult(
                citation=raw_doi,
                status="NO_CITATION_FOUND",
                evidence="No DOI pattern detected.",
                confidence=0.0,
            )

        crossref_result = self._verify_doi_crossref(doi)
        if crossref_result:
            return self._annotate_exact_result(
                crossref_result,
                citation_context=citation_context,
                exact_label="DOI",
                exact_value=doi,
                verification_mode="doi",
            )

        openalex_result = self._verify_doi_openalex_exact(doi)
        if openalex_result:
            return self._annotate_exact_result(
                openalex_result,
                citation_context=citation_context,
                exact_label="DOI",
                exact_value=doi,
                verification_mode="doi",
            )

        result = CitationCheckResult(
            citation=doi,
            status="DOI_NOT_FOUND",
            evidence=(
                "Tra cứu DOI chính xác chưa tìm thấy bản ghi tương ứng trong Crossref hoặc OpenAlex. "
                "Hệ thống không dùng fuzzy match để thay thế cho DOI input."
            ),
            doi=doi,
            source="doi_exact_lookup",
            confidence=0.0,
        )
        result.source_diagnostics = self._source_diagnostics_for_exact(
            source=None,
            verification_mode="doi",
            resolved=False,
        )
        result.search_attempted = True
        result.search_strategy = "exact_lookup"
        result.parse_status = "NOT_PROVIDED"
        result.metadata_consistency = "not_provided"
        result.reason = "The DOI did not resolve to an exact scholarly record in Crossref or OpenAlex."
        return result

    def verify_identifier_exact(
        self,
        raw_identifier: str,
        identifier_type: str,
        citation_context: dict[str, Any] | None = None,
    ) -> CitationCheckResult:
        normalized_type = (identifier_type or "").lower()
        normalized_identifier = self.normalize_exact_identifier(raw_identifier, normalized_type)
        label = _IDENTIFIER_DISPLAY_LABELS.get(normalized_type, "identifier")
        if not normalized_identifier:
            return CitationCheckResult(
                citation=raw_identifier,
                status="NO_CITATION_FOUND",
                evidence=f"Không nhận ra {label} hợp lệ trong input.",
                verification_mode="identifier_exact",
                input_identifier_type=normalized_type or None,
                confidence=0.0,
                reason=f"Could not recognize a valid {label} in the supplied input.",
                source_diagnostics={"openalex": _empty_source_diagnostic("skipped")},
                parse_status="NOT_PROVIDED",
                search_attempted=False,
                search_strategy="exact_lookup",
            )

        lookup_value = self._identifier_lookup_value(normalized_identifier, normalized_type)
        try:
            resp = self._get_client().get(f"{OPENALEX_SEARCH_URL}/{lookup_value}")
            if resp.status_code == 404:
                result = CitationCheckResult(
                    citation=raw_identifier,
                    status="IDENTIFIER_NOT_FOUND",
                    evidence=(
                        f"Tra cứu {label} chính xác chưa tìm thấy bản ghi tương ứng trong OpenAlex. "
                        "Hệ thống không dùng fuzzy match để thay thế cho exact identifier này."
                    ),
                    verification_mode="identifier_exact",
                    input_identifier=normalized_identifier,
                    input_identifier_type=normalized_type,
                    source="identifier_exact_lookup",
                    confidence=0.0,
                )
                result.source_diagnostics = {
                    "openalex": _empty_source_diagnostic("no_match"),
                }
                result.search_attempted = True
                result.search_strategy = "exact_lookup"
                result.parse_status = "NOT_PROVIDED"
                result.metadata_consistency = "not_provided"
                result.reason = f"{label} did not resolve to an exact scholarly record in OpenAlex."
                return result
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            logger.debug("OpenAlex exact identifier lookup failed for %s=%s: %s", normalized_type, normalized_identifier, e)
            result = CitationCheckResult(
                citation=raw_identifier,
                status="IDENTIFIER_NOT_FOUND",
                evidence=(
                    f"Tra cứu {label} chính xác chưa tìm thấy bản ghi tương ứng trong OpenAlex. "
                    "Hệ thống không dùng fuzzy match để thay thế cho exact identifier này."
                ),
                verification_mode="identifier_exact",
                input_identifier=normalized_identifier,
                input_identifier_type=normalized_type,
                source="identifier_exact_lookup",
                confidence=0.0,
            )
            state, detail = _classify_source_exception(e)
            result.source_diagnostics = {
                "openalex": _empty_source_diagnostic(state, detail),
            }
            result.search_attempted = True
            result.search_strategy = "exact_lookup"
            result.parse_status = "NOT_PROVIDED"
            result.metadata_consistency = "not_provided"
            result.reason = f"{label} could not be resolved exactly via OpenAlex."
            return result

        candidate = _normalize_openalex_work(payload)
        matched_identifier = self._extract_identifier_from_openalex_work(payload, normalized_type) or normalized_identifier
        result = CitationCheckResult(
            citation=raw_identifier,
            status="IDENTIFIER_VERIFIED",
            evidence=f"Verified via OpenAlex exact {label} lookup: {candidate.title}",
            doi=candidate.doi,
            title=candidate.title,
            authors=list(candidate.authors or []),
            year=candidate.year,
            source="openalex_exact",
            confidence=1.0,
            metadata={"openalex": payload},
            verification_mode="identifier_exact",
            input_identifier=normalized_identifier,
            input_identifier_type=normalized_type,
            matched_identifier=matched_identifier,
            matched_identifier_type=normalized_type,
            matched_doi=candidate.doi,
            matched_title=candidate.title,
            matched_year=candidate.year,
            matched_authors=list(candidate.authors or []),
            matched_venue=candidate.venue,
        )
        return self._annotate_exact_result(
            result,
            citation_context=citation_context,
            exact_label=label,
            exact_value=normalized_identifier,
            verification_mode="identifier_exact",
        )

    # -- OpenAlex verification ---------------------------------------------

    def _verify_openalex(self, citation: dict[str, Any]) -> CitationCheckResult:
        raw = citation["raw"]
        authors = citation.get("authors") or []
        year = citation.get("year")

        search_parts: list[str] = []
        if authors:
            search_parts.extend(authors[:2])
        if year:
            search_parts.append(str(year))
        search_query = " ".join(search_parts) if search_parts else raw

        if _PYALEX_AVAILABLE and Works is not None:
            try:
                works = Works().search(search_query).get(per_page=3)
                if works:
                    best = self._find_best_match(works, authors, year, raw)
                    if best:
                        return best
                    top = works[0]
                    conf = self._calculate_match_confidence(top, authors, year)
                    status = "VALID" if conf >= 0.7 else ("PARTIAL_MATCH" if conf >= 0.4 else "HALLUCINATED")
                    evidence = (
                        f"Possible match: {top.get('display_name')} (confidence: {conf:.0%})"
                        if status != "HALLUCINATED" else
                        f"Kết quả từ OpenAlex có độ tin cậy rất thấp ({conf:.0%}): {top.get('display_name')}"
                    )
                    return CitationCheckResult(
                        citation=raw, status=status,
                        evidence=evidence,
                        doi=top.get("doi"), title=top.get("display_name"),
                        year=top.get("publication_year"), source="pyalex", confidence=conf,
                    )
            except Exception as e:
                logger.debug("PyAlex search failed: %s", e)

        # HTTP fallback
        try:
            resp = self._get_client().get(OPENALEX_SEARCH_URL, params={"search": search_query, "per-page": 3})
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                top = results[0]
                conf = self._calculate_match_confidence(top, authors, year)
                status = "VALID" if conf >= 0.7 else ("PARTIAL_MATCH" if conf >= 0.4 else "HALLUCINATED")
                evidence = (
                    f"OpenAlex match: {top.get('display_name')} (confidence: {conf:.0%})"
                    if status != "HALLUCINATED" else
                    f"Kết quả từ OpenAlex có độ tin cậy rất thấp ({conf:.0%}): {top.get('display_name')}"
                )
                return CitationCheckResult(
                    citation=raw, status=status,
                    evidence=evidence,
                    doi=top.get("doi"), title=top.get("display_name"),
                    year=top.get("publication_year"), source="openalex_http", confidence=conf,
                )
            return CitationCheckResult(citation=raw, status="HALLUCINATED", evidence="No matching work found in OpenAlex.", confidence=0.0)
        except Exception as e:
            logger.debug("OpenAlex verification failed for %s: %s", raw, e)
            return CitationCheckResult(
                citation=raw,
                status="UNVERIFIED",
                evidence=(
                    "Nguồn tra cứu học thuật tạm thời không phản hồi, nên mục này chưa xác minh được."
                ),
                confidence=0.0,
            )

    # -- matching helpers --------------------------------------------------

    def _find_best_match(self, works: list[dict], authors: list[str] | None, year: int | None, raw: str = "") -> CitationCheckResult | None:
        for w in works:
            conf = self._calculate_match_confidence(w, authors, year)
            if conf >= 0.8:
                return CitationCheckResult(
                    citation=raw or w.get("display_name", ""), status="VALID",
                    evidence=f"High confidence match: {w.get('display_name')}",
                    doi=w.get("doi"), title=w.get("display_name"),
                    year=w.get("publication_year"), source="pyalex", confidence=conf,
                )
        return None

    @staticmethod
    def _calculate_match_confidence(work: dict, authors: list[str] | None, year: int | None) -> float:
        score = 0.0
        factors = 0
        if year and work.get("publication_year"):
            factors += 1
            diff = abs(work["publication_year"] - year)
            score += 1.0 if diff == 0 else (0.5 if diff <= 1 else 0.0)
        if authors:
            work_authors = [a.get("author", {}).get("display_name", "") for a in work.get("authorships", [])]
            if work_authors:
                factors += 1
                best = max(
                    (SequenceMatcher(None, qa.lower(), wa.lower()).ratio() for qa in authors for wa in work_authors),
                    default=0.0,
                )
                score += best
        return score / factors if factors > 0 else 0.0

    @staticmethod
    def _run_candidate_search(
        source_name: str,
        search_fn: Any,
        ref: ReferenceMetadata,
        *,
        limit: int = 5,
    ) -> tuple[list[CandidateWork], dict[str, Any]]:
        try:
            hits = search_fn(ref, limit=limit)
            diagnostic = _empty_source_diagnostic("matched" if hits else "no_match")
            diagnostic["candidate_count"] = len(hits)
            return hits, diagnostic
        except Exception as exc:
            state, detail = _classify_source_exception(exc)
            logger.warning("%s candidate search raised unexpectedly: %s", source_name, exc)
            return [], _empty_source_diagnostic(state, detail)

    @staticmethod
    def _should_use_semantic_cross_check(
        ref: ReferenceMetadata,
        candidates: list[CandidateWork],
        *,
        threshold: float,
    ) -> bool:
        if not candidates:
            return True

        preliminary = choose_best_match(ref, candidates)
        if preliminary.confidence < threshold:
            return True

        best_candidate = preliminary.best_candidate
        if best_candidate and _candidate_has_incomplete_metadata(ref, best_candidate):
            return True

        if _has_source_conflict(ref, candidates):
            return True

        return False

    # -- public API --------------------------------------------------------

    def _metadata_match_to_result(
        self,
        match: MetadataMatchResult,
        raw_citation: str,
    ) -> CitationCheckResult:
        """Map a MetadataMatchResult into a CitationCheckResult."""
        best = match.best_candidate
        cand_dicts: list[dict[str, Any]] = []
        if match.candidate_details:
            for detail in match.candidate_details[:3]:
                cand_dicts.append(dict(detail))
        else:
            for c in match.candidates[:3]:
                cand_dicts.append({
                    "source": c.source,
                    "title": c.title,
                    "authors": list(c.authors or []),
                    "year": c.year,
                    "venue": c.venue,
                    "doi": c.doi,
                    "url": c.url,
                    "external_id": c.external_id,
                    "external_id_type": c.external_id_type,
                })

        evidence_summary = None
        if match.evidence:
            ev = match.evidence
            evidence_summary = (
                f"title={ev.get('title_similarity', 0)} · "
                f"authors={ev.get('author_overlap', 0)} · "
                f"year={ev.get('year_score', 0)} · "
                f"venue={ev.get('venue_similarity', 0)} · "
                f"score={ev.get('final_score', 0)}"
            )
        elif match.status == "PARSE_FAILED":
            evidence_summary = "Reference parsing failed (insufficient metadata)."
        elif match.status == "NO_MATCH_FOUND":
            evidence_summary = "No matching work found in Crossref/OpenAlex/Semantic Scholar."

        completed_metadata = None
        formatted_apa = None
        formatted_bibtex = None
        csl_json = None
        if best and match.status == "METADATA_VERIFIED":
            completed_metadata = build_completed_metadata(best, match.confidence, source=best.source)
            if completed_metadata:
                formatted_apa = format_apa_reference(completed_metadata) or None
                formatted_bibtex = format_bibtex(completed_metadata) or None
                csl_json = build_csl_json(completed_metadata) or None

        return CitationCheckResult(
            citation=raw_citation,
            status=match.status,
            evidence=evidence_summary,
            doi=best.doi if best else None,
            title=best.title if best else None,
            authors=list(best.authors) if best else [],
            year=best.year if best else None,
            source=best.source if best else None,
            confidence=match.confidence,
            verification_mode="metadata_match",
            input_doi=None,
            matched_doi=best.doi if best else None,
            matched_title=best.title if best else None,
            matched_year=best.year if best else None,
            matched_authors=list(best.authors) if best else [],
            matched_venue=best.venue if best else None,
            candidates=cand_dicts,
            warning=match.warning,
            evidence_breakdown=match.evidence or None,
            reason=match.reason,
            field_evidence=match.field_evidence,
            source_diagnostics=match.source_diagnostics,
            parse_status=match.parse_status,
            search_attempted=match.search_attempted,
            search_strategy=match.search_strategy,
            metadata_consistency=None,
            completed_metadata=completed_metadata,
            formatted_apa=formatted_apa,
            formatted_bibtex=formatted_bibtex,
            csl_json=csl_json,
        )

    def _verify_metadata_match(self, citation: dict[str, Any]) -> CitationCheckResult:
        """Verify a non-DOI citation via Crossref+OpenAlex metadata matching."""
        raw = citation.get("raw", "") or ""
        ref = parse_reference_metadata(raw)
        settings = get_settings()
        source_diagnostics: dict[str, Any] = {
            "crossref": _empty_source_diagnostic("skipped"),
            "openalex": _empty_source_diagnostic("skipped"),
            "semantic_scholar": _empty_source_diagnostic(
                "disabled" if not settings.semantic_scholar_enabled else "skipped"
            ),
        }

        # Pre-fill missing fields from the extracted citation dict.
        if not ref.authors and citation.get("authors"):
            ref.authors = [str(a) for a in citation["authors"] if a]
        if not ref.year and citation.get("year"):
            try:
                ref.year = int(citation["year"])
            except (ValueError, TypeError):
                pass

        search_ref = ref
        search_strategy = "parsed_metadata"
        parse_status = "HIGH_CONFIDENCE" if ref.confidence >= 0.70 else "LOW_CONFIDENCE"

        if not ref.title or ref.confidence <= _LOW_PARSE_CONFIDENCE:
            fallback_title = _build_fallback_title_query(raw, ref)
            if fallback_title:
                search_ref = ReferenceMetadata(
                    raw=raw,
                    title=fallback_title,
                    authors=list(ref.authors or []),
                    year=ref.year,
                    venue=ref.venue,
                    volume=ref.volume,
                    issue=ref.issue,
                    pages=ref.pages,
                    doi=ref.doi,
                    confidence=max(ref.confidence, _LOW_PARSE_CONFIDENCE + 0.05),
                )
                parse_status = "LOW_CONFIDENCE_FALLBACK_USED"
                search_strategy = "raw_title_fallback"
            else:
                reason = _build_match_reason(
                    "PARSE_FAILED",
                    None,
                    source_diagnostics=source_diagnostics,
                    parse_status="UNPARSABLE",
                )
                warning = "Could not extract enough metadata or a title-like phrase to search scholarly sources."
                return CitationCheckResult(
                    citation=raw,
                    status="PARSE_FAILED",
                    evidence="Reference parsing failed (no title or low confidence).",
                    verification_mode="metadata_match",
                    warning=warning,
                    reason=reason,
                    source_diagnostics=source_diagnostics,
                    parse_status="UNPARSABLE",
                    search_attempted=False,
                    search_strategy=None,
                )

        if not search_ref.title:
            reason = _build_match_reason(
                "PARSE_FAILED",
                None,
                source_diagnostics=source_diagnostics,
                parse_status="UNPARSABLE",
            )
            return CitationCheckResult(
                citation=raw,
                status="PARSE_FAILED",
                evidence="Reference parsing failed (no title or low confidence).",
                verification_mode="metadata_match",
                warning="Could not extract enough metadata (title) to attempt matching.",
                reason=reason,
                source_diagnostics=source_diagnostics,
                parse_status="UNPARSABLE",
                search_attempted=False,
                search_strategy=None,
            )

        crossref_hits, source_diagnostics["crossref"] = self._run_candidate_search(
            "crossref",
            search_crossref_candidates,
            search_ref,
            limit=5,
        )
        openalex_hits, source_diagnostics["openalex"] = self._run_candidate_search(
            "openalex",
            search_openalex_candidates,
            search_ref,
            limit=5,
        )
        candidates = _merge_candidates(crossref_hits, openalex_hits)
        if settings.semantic_scholar_enabled and search_ref.title:
            if self._should_use_semantic_cross_check(
                search_ref,
                candidates,
                threshold=settings.semantic_scholar_fallback_threshold,
            ):
                semantic_hits, source_diagnostics["semantic_scholar"] = self._run_candidate_search(
                    "semantic_scholar",
                    search_semantic_scholar_candidates,
                    search_ref,
                    limit=5,
                )
                candidates = _merge_candidates(candidates, semantic_hits)

        match = choose_best_match(search_ref, candidates)
        match.source_diagnostics = source_diagnostics
        match.parse_status = parse_status
        match.search_attempted = True
        match.search_strategy = search_strategy

        degraded_sources = [
            source
            for source, diagnostic in source_diagnostics.items()
            if isinstance(diagnostic, dict) and diagnostic.get("state") in _SOURCE_ERROR_STATES
        ]
        if not candidates and degraded_sources:
            match.status = "UNVERIFIED"
            match.confidence = 0.0
            match.warning = (
                "Could not complete verification because one or more scholarly sources were unavailable."
            )
            match.best_candidate = None
            match.candidates = []
            match.candidate_details = []
            match.evidence = {}
            match.field_evidence = None

        match.reason = _build_match_reason(
            match.status,
            match.field_evidence,
            source_diagnostics=source_diagnostics,
            parse_status=parse_status,
        )
        return self._metadata_match_to_result(match, raw_citation=raw)

    @staticmethod
    def _exact_result_priority(result: CitationCheckResult) -> int:
        if result.status == "DOI_VERIFIED":
            return 300
        if result.status != "IDENTIFIER_VERIFIED":
            return 0
        identifier_type = (result.input_identifier_type or result.matched_identifier_type or "").lower()
        if identifier_type in {"pmid", "pmcid"}:
            return 200
        if identifier_type == "openalex":
            return 150
        return 100

    @staticmethod
    def _result_work_key(result: CitationCheckResult) -> tuple[str, str] | None:
        doi = CitationChecker.normalize_doi(result.matched_doi or result.doi or "")
        if doi:
            return ("doi", doi)

        completed = result.completed_metadata or {}
        if isinstance(completed, dict):
            external_id = completed.get("external_id")
            external_type = completed.get("external_id_type")
            if isinstance(external_id, str) and external_id.strip():
                key_type = str(external_type or "external").lower()
                return (key_type, external_id.strip().lower())

        title = result.matched_title or result.title
        year = result.matched_year if result.matched_year is not None else result.year
        if title and year is not None:
            return ("title_year", f"{normalize_title(title)}::{year}")
        return None

    def _dedupe_exact_verified_results(self, results: list[CitationCheckResult]) -> list[CitationCheckResult]:
        deduped: list[CitationCheckResult] = []
        seen_exact: dict[tuple[str, str], tuple[int, int]] = {}
        for result in results:
            priority = self._exact_result_priority(result)
            if priority <= 0:
                deduped.append(result)
                continue

            key = self._result_work_key(result)
            if key is None:
                deduped.append(result)
                continue

            current = seen_exact.get(key)
            if current is None:
                seen_exact[key] = (len(deduped), priority)
                deduped.append(result)
                continue

            idx, previous_priority = current
            if priority > previous_priority:
                deduped[idx] = result
                seen_exact[key] = (idx, priority)

        return deduped

    def verify(self, text: str) -> list[CitationCheckResult]:
        """Verify all citations found in *text*."""
        citations = self.extract_citations(text)
        if not citations:
            return [CitationCheckResult(
                citation="N/A",
                status="NO_CITATION_FOUND",
                evidence=(
                    "Mình chưa thấy DOI, exact identifier hoặc citation đủ rõ. "
                    "Các định dạng hỗ trợ gồm DOI, PMID/PMCID, OpenAlex ID, APA/reference, hoặc Author-Year."
                ),
                verification_mode="none",
            )]

        results: list[CitationCheckResult] = []
        for c in citations:
            if c["type"] == "doi":
                doi_in = c["doi"]
                result = self.verify_doi_exact(doi_in, citation_context=c)
                result.verification_mode = "doi"
                result.input_doi = doi_in
                if result.status == "DOI_VERIFIED":
                    result.matched_doi = result.doi
                    result.matched_title = result.title
                    result.matched_year = result.year
                    result.matched_authors = list(result.authors or [])
                results.append(result)
            elif c["type"] in {"pmid", "pmcid", "openalex"}:
                identifier_value = c.get("identifier") or c.get("exact_raw") or c["raw"]
                results.append(self.verify_identifier_exact(identifier_value, c["type"], citation_context=c))
            else:
                results.append(self._verify_metadata_match(c))

        results = self._dedupe_exact_verified_results(results)

        # Safety-net post-processing: suppress fragmentary non-exact results that
        # overlap with an exact-verified entry (same year + title contained within
        # the fragment's raw text).
        exact_verified = [
            r for r in results
            if r.status in {"DOI_VERIFIED", "IDENTIFIER_VERIFIED"} and r.year and r.title
        ]
        if exact_verified:
            merged: list[CitationCheckResult] = []
            for r in results:
                if r.status in {"DOI_VERIFIED", "IDENTIFIER_VERIFIED"}:
                    merged.append(r)
                    continue
                fragment_statuses = (
                    "HALLUCINATED", "PARTIAL_MATCH", "VALID",
                    "METADATA_VERIFIED", "LIKELY_MATCH", "POSSIBLE_MATCH",
                    "AMBIGUOUS_MATCH", "UNVERIFIED_NO_DOI", "NO_MATCH_FOUND", "PARSE_FAILED",
                )
                if r.status in fragment_statuses and r.year:
                    overlapped = any(
                        dv.year == r.year and dv.title and r.citation and dv.title in r.citation
                        for dv in exact_verified
                    )
                    if overlapped:
                        continue
                merged.append(r)
            results = merged

        return results

    def verify_reference_list(self, references: list[str]) -> list[CitationCheckResult]:
        results: list[CitationCheckResult] = []
        for ref in references:
            results.extend(self.verify(ref))
        return results

    def get_statistics(self, results: list[CitationCheckResult]) -> dict[str, Any]:
        checked = [r for r in results if r.status != "NO_CITATION_FOUND"]
        total = len(checked)
        if total == 0:
            return {
                "total": 0,
                "no_citation_found": True,
                "valid": 0,
                "doi_verified": 0,
                "doi_not_found": 0,
                "identifier_verified": 0,
                "identifier_not_found": 0,
                "partial_match": 0,
                "hallucinated": 0,
                "unverified": 0,
                "metadata_verified": 0,
                "likely_match": 0,
                "possible_match": 0,
                "ambiguous_match": 0,
                "unverified_no_doi": 0,
                "no_match_found": 0,
                "parse_failed": 0,
                "avg_confidence": 0.0,
                "verified_rate": 0.0,
                "risk_rate": 0.0,
            }
        stats = {
            "total": total,
            "no_citation_found": False,
            "valid": sum(1 for r in checked if r.status == "VALID"),
            "doi_verified": sum(1 for r in checked if r.status == "DOI_VERIFIED"),
            "doi_not_found": sum(1 for r in checked if r.status == "DOI_NOT_FOUND"),
            "identifier_verified": sum(1 for r in checked if r.status == "IDENTIFIER_VERIFIED"),
            "identifier_not_found": sum(1 for r in checked if r.status == "IDENTIFIER_NOT_FOUND"),
            "partial_match": sum(1 for r in checked if r.status == "PARTIAL_MATCH"),
            "hallucinated": sum(1 for r in checked if r.status == "HALLUCINATED"),
            "unverified": sum(1 for r in checked if r.status == "UNVERIFIED"),
            "metadata_verified": sum(1 for r in checked if r.status == "METADATA_VERIFIED"),
            "likely_match": sum(1 for r in checked if r.status == "LIKELY_MATCH"),
            "possible_match": sum(1 for r in checked if r.status == "POSSIBLE_MATCH"),
            "ambiguous_match": sum(1 for r in checked if r.status == "AMBIGUOUS_MATCH"),
            "unverified_no_doi": sum(1 for r in checked if r.status == "UNVERIFIED_NO_DOI"),
            "no_match_found": sum(1 for r in checked if r.status == "NO_MATCH_FOUND"),
            "parse_failed": sum(1 for r in checked if r.status == "PARSE_FAILED"),
            "avg_confidence": sum(r.confidence for r in checked) / total,
        }
        stats["verified_rate"] = (
            stats["valid"] + stats["doi_verified"]
            + stats["identifier_verified"]
            + stats["metadata_verified"] + stats["likely_match"]
        ) / total
        stats["risk_rate"] = (
            stats["hallucinated"] + stats["doi_not_found"]
            + stats["identifier_not_found"]
            + stats["no_match_found"] + stats["parse_failed"]
        ) / total
        return stats

    def close(self) -> None:
        if self._http_client:
            self._http_client.close()
            self._http_client = None

    def __del__(self) -> None:
        self.close()


# Singleton
citation_checker = CitationChecker()
