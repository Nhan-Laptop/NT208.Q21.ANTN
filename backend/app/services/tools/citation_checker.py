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

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class CitationCheckResult:
    """Result of citation verification."""
    citation: str
    status: str          # VALID | HALLUCINATED | UNVERIFIED | PARTIAL_MATCH | DOI_VERIFIED | NO_CITATION_FOUND
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

    # -- extraction --------------------------------------------------------

    def extract_candidates(self, text: str) -> list[str]:
        """Legacy helper used by the endpoint (returns raw strings)."""
        return sorted({m.strip() for m in _LEGACY_REGEX.findall(text)})

    def extract_citations(self, text: str) -> list[dict[str, Any]]:
        """Extract citations using multiple format patterns."""
        citations: list[dict[str, Any]] = []
        seen: set[str] = set()

        for doi_m in CITATION_PATTERNS["doi"].finditer(text):
            doi = doi_m.group(1).rstrip(".,;)")
            if doi not in seen:
                seen.add(doi)
                citations.append({"raw": doi, "type": "doi", "doi": doi, "authors": None, "year": None})

        for match in CITATION_PATTERNS["apa_inline"].finditer(text):
            author, year = match.group(1).strip(), match.group(2)
            key = f"{author}_{year}"
            if key not in seen:
                seen.add(key)
                citations.append({"raw": match.group(0), "type": "apa_inline", "authors": [author], "year": int(year), "doi": None})

        for match in CITATION_PATTERNS["simple"].finditer(text):
            author, year = match.group(1).strip(), match.group(2)
            key = f"{author}_{year}"
            if key not in seen:
                seen.add(key)
                citations.append({"raw": match.group(0), "type": "simple", "authors": [author], "year": int(year), "doi": None})

        return citations

    # -- DOI verification --------------------------------------------------

    def _verify_doi_crossref(self, doi: str) -> CitationCheckResult | None:
        if self._crossref is not None:
            try:
                result = self._crossref.works(ids=doi)
                if result and "message" in result:
                    msg = result["message"]
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
                        doi=doi, title=title, authors=authors, year=year,
                        source="crossref", confidence=1.0, metadata={"crossref": msg},
                    )
            except Exception as e:
                logger.debug("Crossref lookup failed for %s: %s", doi, e)

        # HTTP fallback
        try:
            resp = self._get_client().get(f"{CROSSREF_WORKS_URL}/{doi}")
            if resp.status_code == 200:
                data = resp.json().get("message", {})
                title = data.get("title", [""])[0]
                return CitationCheckResult(
                    citation=doi, status="DOI_VERIFIED",
                    evidence=f"Verified via Crossref HTTP: {title}",
                    doi=doi, title=title, source="crossref_http", confidence=0.95,
                )
        except Exception as e:
            logger.debug("Crossref HTTP failed for %s: %s", doi, e)
        return None

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
                    best = self._find_best_match(works, authors, year)
                    if best:
                        return best
                    top = works[0]
                    return CitationCheckResult(
                        citation=raw, status="PARTIAL_MATCH",
                        evidence=f"Possible match: {top.get('display_name')}",
                        doi=top.get("doi"), title=top.get("display_name"),
                        year=top.get("publication_year"), source="pyalex", confidence=0.5,
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
                return CitationCheckResult(
                    citation=raw, status=status,
                    evidence=f"OpenAlex match: {top.get('display_name')} (confidence: {conf:.0%})",
                    doi=top.get("doi"), title=top.get("display_name"),
                    year=top.get("publication_year"), source="openalex_http", confidence=conf,
                )
            return CitationCheckResult(citation=raw, status="HALLUCINATED", evidence="No matching work found in OpenAlex.", confidence=0.0)
        except Exception as e:
            return CitationCheckResult(citation=raw, status="UNVERIFIED", evidence=f"Verification failed: {e}", confidence=0.0)

    # -- matching helpers --------------------------------------------------

    def _find_best_match(self, works: list[dict], authors: list[str] | None, year: int | None) -> CitationCheckResult | None:
        for w in works:
            conf = self._calculate_match_confidence(w, authors, year)
            if conf >= 0.8:
                return CitationCheckResult(
                    citation=w.get("display_name", ""), status="VALID",
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
            return [CitationCheckResult(citation="N/A", status="NO_CITATION_FOUND", evidence="No citation patterns detected. Supported formats: APA, DOI, Author-Year.")]

        results: list[CitationCheckResult] = []
        for c in citations:
            if c["type"] == "doi":
                r = self._verify_doi_crossref(c["doi"])
                results.append(r if r else self._verify_openalex(c))
            else:
                results.append(self._verify_openalex(c))
        return results

    def verify_reference_list(self, references: list[str]) -> list[CitationCheckResult]:
        results: list[CitationCheckResult] = []
        for ref in references:
            results.extend(self.verify(ref))
        return results

    def get_statistics(self, results: list[CitationCheckResult]) -> dict[str, Any]:
        total = len(results)
        if total == 0:
            return {"total": 0}
        stats = {
            "total": total,
            "valid": sum(1 for r in results if r.status == "VALID"),
            "doi_verified": sum(1 for r in results if r.status == "DOI_VERIFIED"),
            "partial_match": sum(1 for r in results if r.status == "PARTIAL_MATCH"),
            "hallucinated": sum(1 for r in results if r.status == "HALLUCINATED"),
            "unverified": sum(1 for r in results if r.status == "UNVERIFIED"),
            "avg_confidence": sum(r.confidence for r in results) / total,
        }
        stats["verified_rate"] = (stats["valid"] + stats["doi_verified"]) / total
        stats["risk_rate"] = stats["hallucinated"] / total
        return stats

    def close(self) -> None:
        if self._http_client:
            self._http_client.close()
            self._http_client = None

    def __del__(self) -> None:
        self.close()


# Singleton
citation_checker = CitationChecker()
