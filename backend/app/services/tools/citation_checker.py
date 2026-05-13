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
    """Result of citation verification."""
    citation: str
    status: str          # VALID | HALLUCINATED | UNVERIFIED | PARTIAL_MATCH | DOI_VERIFIED | DOI_NOT_FOUND | NO_CITATION_FOUND
    evidence: str | None = None
    doi: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    source: str | None = None
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


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
            )]

        results: list[CitationCheckResult] = []
        for c in citations:
            if c["type"] == "doi":
                results.append(self.verify_doi_exact(c["doi"]))
            else:
                results.append(self._verify_openalex(c))

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
                if r.status in ("HALLUCINATED", "PARTIAL_MATCH", "VALID") and r.year:
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
            "avg_confidence": sum(r.confidence for r in checked) / total,
        }
        stats["verified_rate"] = (stats["valid"] + stats["doi_verified"]) / total
        stats["risk_rate"] = (stats["hallucinated"] + stats["doi_not_found"]) / total
        return stats

    def close(self) -> None:
        if self._http_client:
            self._http_client.close()
            self._http_client = None

    def __del__(self) -> None:
        self.close()


# Singleton
citation_checker = CitationChecker()
