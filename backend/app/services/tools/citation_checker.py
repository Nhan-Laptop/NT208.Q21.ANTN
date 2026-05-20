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

_REF_SECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"\n\s*references?\s*\n", re.IGNORECASE),
    re.compile(r"\n\s*bibliography\s*\n", re.IGNORECASE),
    re.compile(r"\n\s*tài\s+liệu\s+tham\s+khảo\s*\n", re.IGNORECASE),
]
_NUMBERED_REF_LINE_RE = re.compile(
    r"^\s*(?:\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}[.)])\s+"
)
_DOI_NORMALIZE_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Helpers for citation dedup
# ---------------------------------------------------------------------------


def _inside_doi_block(pos: int, doi_blocks: set[int], block_starts: list[int], blocks: list[str]) -> bool:
    """Return True if *pos* (character offset in normalized text) falls inside
    any block that is known to contain a DOI."""
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
    verification_mode: str | None = None  # "doi" | "metadata_match" | "none"
    input_doi: str | None = None
    matched_doi: str | None = None
    matched_title: str | None = None
    matched_year: int | None = None
    matched_authors: list[str] = field(default_factory=list)
    matched_venue: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    warning: str | None = None
    evidence_breakdown: dict[str, float] | None = None


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
    source: str          # e.g., "crossref", "openalex"
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
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
    evidence: dict[str, Any] = field(default_factory=dict)
    warning: str | None = None



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

    # 6. Volume, Issue, Pages
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


def _merge_candidates(crossref_results: list[CandidateWork], openalex_results: list[CandidateWork]) -> list[CandidateWork]:
    """Merge candidates from Crossref + OpenAlex, deduping by DOI then by normalized title."""
    merged: list[CandidateWork] = []
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()

    def _add(cand: CandidateWork) -> None:
        if cand.doi:
            key = cand.doi.lower()
            if key in seen_dois:
                return
            seen_dois.add(key)
        elif cand.title:
            tkey = normalize_title(cand.title)
            if tkey and tkey in seen_titles:
                return
            if tkey:
                seen_titles.add(tkey)
        merged.append(cand)

    for c in crossref_results:
        _add(c)
    for c in openalex_results:
        _add(c)
    return merged


def score_candidate(ref: ReferenceMetadata, candidate: CandidateWork) -> dict[str, Any]:
    """Calculate similarity scores and final matching score between reference and candidate work."""
    # 1. Title similarity
    title_similarity = 0.0
    if ref.title and candidate.title:
        ref_title_norm = normalize_title(ref.title)
        cand_title_norm = normalize_title(candidate.title)
        title_similarity = SequenceMatcher(None, ref_title_norm, cand_title_norm).ratio()

    # 2. Author overlap
    author_overlap = 0.0
    if ref.authors and candidate.authors:
        ref_authors_norm = [normalize_author_name(a) for a in ref.authors if a]
        cand_authors_norm = [normalize_author_name(a) for a in candidate.authors if a]
        
        if ref_authors_norm:
            matches = 0
            for ra in ref_authors_norm:
                if any(ra == ca or SequenceMatcher(None, ra, ca).ratio() > 0.85 for ca in cand_authors_norm):
                    matches += 1
            author_overlap = matches / len(ref_authors_norm)

    # 3. Year score
    year_score = 0.0
    if ref.year is not None and candidate.year is not None:
        diff = abs(ref.year - candidate.year)
        if diff == 0:
            year_score = 1.0
        elif diff == 1:
            year_score = 0.5
        else:
            year_score = 0.0

    # 4. Venue similarity
    venue_similarity = 0.0
    if ref.venue and candidate.venue:
        ref_venue_norm = normalize_venue(ref.venue)
        cand_venue_norm = normalize_venue(candidate.venue)
        venue_similarity = SequenceMatcher(None, ref_venue_norm, cand_venue_norm).ratio()

    # 5. Page/Volume bonus (1.0 if at least 2 match, 0.0 otherwise)
    page_volume_bonus = 0.0
    matches_count = 0
    if ref.volume and candidate.volume and ref.volume.strip() == candidate.volume.strip():
        matches_count += 1
    if ref.issue and candidate.issue and ref.issue.strip() == candidate.issue.strip():
        matches_count += 1
    if ref.pages and candidate.pages:
        p1 = ref.pages.strip().replace("–", "-")
        p2 = candidate.pages.strip().replace("–", "-")
        if p1 == p2:
            matches_count += 1
    if matches_count >= 2:
        page_volume_bonus = 1.0

    # 6. Final Score formula
    final_score = (
        0.45 * title_similarity +
        0.25 * author_overlap +
        0.15 * year_score +
        0.10 * venue_similarity +
        0.05 * page_volume_bonus
    )

    return {
        "title_similarity": round(title_similarity, 3),
        "author_overlap": round(author_overlap, 3),
        "year_score": round(year_score, 3),
        "venue_similarity": round(venue_similarity, 3),
        "page_volume_bonus": round(page_volume_bonus, 3),
        "final_score": round(final_score, 3)
    }


def choose_best_match(ref: ReferenceMetadata, candidates: list[CandidateWork]) -> MetadataMatchResult:
    """Evaluate and select the best candidate match, assigning matching status based on safety rules."""
    if not ref or ref.confidence <= 0.4 or not ref.title:
        return MetadataMatchResult(
            reference=ref,
            status="PARSE_FAILED",
            confidence=0.0,
            warning="Parsing failed or title is missing in reference metadata."
        )

    if not candidates:
        warning = None
        if not ref.doi:
            warning = "Warning: Citation does not contain DOI, matched via metadata search."
        return MetadataMatchResult(
            reference=ref,
            status="NO_MATCH_FOUND",
            confidence=0.0,
            warning=warning
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

    # Safety Caps Rules:
    # Rule 1: title_similarity < 0.75 -> max POSSIBLE_MATCH
    if best_evidence["title_similarity"] < 0.75:
        if status in ("METADATA_VERIFIED", "LIKELY_MATCH"):
            status = "POSSIBLE_MATCH"

    # Rule 2: author_overlap == 0 and year_score < 1 -> max POSSIBLE_MATCH
    if best_evidence["author_overlap"] == 0.0 and best_evidence["year_score"] < 1.0:
        if status in ("METADATA_VERIFIED", "LIKELY_MATCH"):
            status = "POSSIBLE_MATCH"

    # Ambiguity check: top1_score - top2_score < 0.05 and top1_score >= 0.65
    if len(scored_candidates) > 1 and top1_score >= 0.65:
        top2_score = scored_candidates[1][1]["final_score"]
        if (top1_score - top2_score) < 0.05:
            status = "AMBIGUOUS_MATCH"

    # Set warnings if input does not have DOI
    warning = None
    if not ref.doi:
        warning = "Warning: Citation does not contain DOI, matched via metadata search."

    return MetadataMatchResult(
        reference=ref,
        status=status,
        confidence=top1_score,
        best_candidate=best_cand,
        candidates=top_3,
        evidence=best_evidence,
        warning=warning
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

    def extract_dois(self, text: str) -> list[str]:
        normalized_text = self._normalize_input_text(text)
        dois: set[str] = set()
        for match in CITATION_PATTERNS["doi"].finditer(normalized_text):
            doi = self._normalize_doi(match.group(1))
            if doi:
                dois.add(doi)
        return sorted(dois)

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

        # Identify blocks that contain a DOI.
        doi_blocks: set[int] = set()
        for i, blk in enumerate(blocks):
            if CITATION_PATTERNS["doi"].search(blk):
                doi_blocks.add(i)

        # DOI extraction from whole text and extracted blocks.
        for segment in [normalized_text, *blocks]:
            for doi_m in CITATION_PATTERNS["doi"].finditer(segment):
                doi = self._normalize_doi(doi_m.group(1))
                if not doi:
                    continue
                _add_citation(
                    {
                        "raw": doi,
                        "type": "doi",
                        "doi": doi,
                        "authors": None,
                        "year": None,
                    },
                    key=f"doi:{doi.lower()}",
                )

        # Structured extraction from blocks (multiline references, numbered lists).
        # Skip blocks that already have a DOI — the DOI entry is authoritative
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
        # Skip matches that fall within a DOI block.
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

    def verify_doi_exact(self, raw_doi: str) -> CitationCheckResult:
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
            return crossref_result

        openalex_result = self._verify_doi_openalex_exact(doi)
        if openalex_result:
            return openalex_result

        return CitationCheckResult(
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

    # -- public API --------------------------------------------------------

    def _metadata_match_to_result(
        self,
        match: MetadataMatchResult,
        raw_citation: str,
    ) -> CitationCheckResult:
        """Map a MetadataMatchResult into a CitationCheckResult."""
        best = match.best_candidate
        cand_dicts: list[dict[str, Any]] = []
        for c in match.candidates[:3]:
            cand_dicts.append({
                "source": c.source,
                "title": c.title,
                "authors": list(c.authors or []),
                "year": c.year,
                "venue": c.venue,
                "doi": c.doi,
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
            evidence_summary = "No matching work found in Crossref/OpenAlex."

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
        )

    def _verify_metadata_match(self, citation: dict[str, Any]) -> CitationCheckResult:
        """Verify a non-DOI citation via Crossref+OpenAlex metadata matching."""
        raw = citation.get("raw", "") or ""
        ref = parse_reference_metadata(raw)

        # Pre-fill missing fields from the extracted citation dict.
        if not ref.authors and citation.get("authors"):
            ref.authors = [str(a) for a in citation["authors"] if a]
        if not ref.year and citation.get("year"):
            try:
                ref.year = int(citation["year"])
            except (ValueError, TypeError):
                pass

        # If parsing failed or no title, abort before any network call.
        if not ref.title or ref.confidence <= 0.4:
            return CitationCheckResult(
                citation=raw,
                status="PARSE_FAILED",
                evidence="Reference parsing failed (no title or low confidence).",
                verification_mode="metadata_match",
                warning="Could not extract enough metadata (title) to attempt matching.",
            )

        # Independent try/except so one API failure doesn't kill the other.
        crossref_hits: list[CandidateWork] = []
        openalex_hits: list[CandidateWork] = []
        try:
            crossref_hits = search_crossref_candidates(ref, limit=5)
        except Exception as e:  # defensive — searcher already swallows, but be safe.
            logger.warning("search_crossref_candidates raised unexpectedly: %s", e)
        try:
            openalex_hits = search_openalex_candidates(ref, limit=5)
        except Exception as e:
            logger.warning("search_openalex_candidates raised unexpectedly: %s", e)

        candidates = _merge_candidates(crossref_hits, openalex_hits)
        match = choose_best_match(ref, candidates)
        return self._metadata_match_to_result(match, raw_citation=raw)

    def verify(self, text: str) -> list[CitationCheckResult]:
        """Verify all citations found in *text*."""
        citations = self.extract_citations(text)
        if not citations:
            return [CitationCheckResult(
                citation="N/A",
                status="NO_CITATION_FOUND",
                evidence=(
                    "Mình chưa thấy DOI hoặc citation đủ rõ. Các định dạng hỗ trợ gồm DOI, APA/reference, hoặc Author-Year."
                ),
                verification_mode="none",
            )]

        results: list[CitationCheckResult] = []
        for c in citations:
            if c["type"] == "doi":
                doi_in = c["doi"]
                result = self.verify_doi_exact(doi_in)
                result.verification_mode = "doi"
                result.input_doi = doi_in
                if result.status == "DOI_VERIFIED":
                    result.matched_doi = result.doi
                    result.matched_title = result.title
                    result.matched_year = result.year
                    result.matched_authors = list(result.authors or [])
                results.append(result)
            else:
                results.append(self._verify_metadata_match(c))

        # Safety-net post-processing: suppress fragmentary non-DOI results that
        # overlap with a DOI_VERIFIED entry (same year + title contained within
        # the fragment's raw text).
        doi_verified = [r for r in results if r.status == "DOI_VERIFIED" and r.year and r.title]
        if doi_verified:
            merged: list[CitationCheckResult] = []
            for r in results:
                if r.status == "DOI_VERIFIED":
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
                        for dv in doi_verified
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
            + stats["metadata_verified"] + stats["likely_match"]
        ) / total
        stats["risk_rate"] = (
            stats["hallucinated"] + stats["doi_not_found"]
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
