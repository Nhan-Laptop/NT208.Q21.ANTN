"""
Retraction Scanner — check DOIs for retraction / concern status.

Data sources (auto-selected):
1. Crossref ``update-to`` field (most authoritative)   — via habanero or httpx
2. OpenAlex ``is_retracted`` flag                       — via httpx
3. PubPeer community feedback                            — via httpx
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Any
from enum import Enum

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dep: habanero
# ---------------------------------------------------------------------------
_HABANERO_AVAILABLE = False
try:
    from habanero import Crossref as _HabaneroCrossref
    _HABANERO_AVAILABLE = True
except ImportError:
    _HabaneroCrossref = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Patterns / URLs
# ---------------------------------------------------------------------------
DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", flags=re.IGNORECASE)
PMID_REGEX = re.compile(r"PMID[:\s]*(\d+)", flags=re.IGNORECASE)

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
PUBPEER_API_URL = "https://pubpeer.com/v1/publications"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CrossrefUpdate:
    type: str
    date: str | None = None
    doi: str | None = None
    label: str | None = None


@dataclass(slots=True)
class PubPeerInfo:
    has_comments: bool = False
    comment_count: int = 0
    url: str | None = None
    latest_comment_date: str | None = None
    concerns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RetractionResult:
    """Result for a single DOI.

    The fields ``doi``, ``status``, ``title``, ``pubpeer_comments``,
    ``pubpeer_url``, ``risk_level`` are kept for backward compatibility
    with the existing ``RetractionItem`` Pydantic schema.
    """
    doi: str
    status: str                 # ACTIVE | RETRACTED | CORRECTED | CONCERN | UNKNOWN | ERROR | NO_DOI_FOUND | UNVERIFIED
    title: str | None = None

    # backward-compat flat fields
    pubpeer_comments: int = 0
    pubpeer_url: str | None = None
    risk_level: str = "UNKNOWN"

    # enhanced V2 fields (ignored by current schema, but available)
    risk_level_enum: RiskLevel = RiskLevel.NONE
    risk_factors: list[str] = field(default_factory=list)
    crossref_updates: list[CrossrefUpdate] = field(default_factory=list)
    has_retraction: bool = False
    has_correction: bool = False
    has_concern: bool = False
    is_retracted_openalex: bool = False
    openalex_id: str | None = None
    pubpeer_info: PubPeerInfo | None = None
    publication_year: int | None = None
    journal: str | None = None
    authors: list[str] = field(default_factory=list)
    sources_checked: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

class RetractionScanner:
    """
    Multi-source retraction scanner.

    Priority: Crossref update-to > OpenAlex is_retracted > PubPeer comments.
    """

    def __init__(self) -> None:
        self._crossref = _HabaneroCrossref() if _HABANERO_AVAILABLE else None
        self._http_client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._http_client is None:
            transport = httpx.HTTPTransport(retries=2)
            self._http_client = httpx.Client(
                timeout=12.0,
                headers={"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"},
                transport=transport,
            )
        return self._http_client

    def extract_doi(self, text: str) -> list[str]:
        return sorted({m.lower().rstrip(".,;:)>]}") for m in DOI_REGEX.findall(text)})

    # -- Crossref ----------------------------------------------------------

    def _check_crossref(self, doi: str) -> tuple[list[CrossrefUpdate], dict[str, Any] | None]:
        updates: list[CrossrefUpdate] = []
        metadata: dict[str, Any] | None = None

        if self._crossref is not None:
            try:
                result = self._crossref.works(ids=doi)
                if result and "message" in result:
                    msg = result["message"]
                    metadata = msg
                    for u in msg.get("update-to", []):
                        updates.append(CrossrefUpdate(
                            type=u.get("type", "unknown"),
                            date=str(u.get("updated", {}).get("date-parts", [[None]])[0][0]),
                            doi=u.get("DOI"), label=u.get("label"),
                        ))
                    return updates, metadata
            except Exception as e:
                logger.debug("Crossref habanero failed for %s: %s", doi, e)

        # HTTP fallback
        try:
            resp = self._get_client().get(f"{CROSSREF_WORKS_URL}/{doi}")
            if resp.status_code == 200:
                msg = resp.json().get("message", {})
                metadata = msg
                for u in msg.get("update-to", []):
                    dp = u.get("updated", {}).get("date-parts", [[None]])
                    date_str = "-".join(str(d) for d in dp[0] if d) if dp and dp[0] else None
                    updates.append(CrossrefUpdate(
                        type=u.get("type", "unknown"), date=date_str,
                        doi=u.get("DOI"), label=u.get("label"),
                    ))
        except Exception as e:
            logger.debug("Crossref HTTP failed for %s: %s", doi, e)

        return updates, metadata

    # -- OpenAlex ----------------------------------------------------------

    def _check_openalex(self, doi: str) -> tuple[bool, dict[str, Any] | None]:
        try:
            resp = self._get_client().get(OPENALEX_WORKS_URL, params={"filter": f"doi:{doi}"})
            resp.raise_for_status()
            rows = resp.json().get("results", [])
            if rows:
                return rows[0].get("is_retracted", False), rows[0]
        except Exception as e:
            logger.debug("OpenAlex failed for %s: %s", doi, e)
        return False, None

    # -- PubPeer -----------------------------------------------------------

    def _check_pubpeer(self, doi: str) -> PubPeerInfo:
        info = PubPeerInfo()
        try:
            resp = self._get_client().get(PUBPEER_API_URL, params={"doi": doi})
            if resp.status_code == 200:
                pubs = resp.json().get("publications", [])
                if pubs:
                    pub = pubs[0]
                    info.has_comments = True
                    info.comment_count = pub.get("total_comments", 0)
                    info.url = pub.get("url") or f"https://pubpeer.com/search?q={doi}"
                    comments = pub.get("comments", [])
                    if comments:
                        dates = [c.get("created_at") for c in comments if c.get("created_at")]
                        if dates:
                            info.latest_comment_date = max(dates)
                        concern_kws = ["fraud", "fabrication", "manipulation", "duplicate",
                                       "plagiarism", "misconduct", "retract", "concern",
                                       "fake", "suspicious", "error"]
                        for c in comments[:10]:
                            txt = c.get("body", "").lower()
                            for kw in concern_kws:
                                if kw in txt and kw not in info.concerns:
                                    info.concerns.append(kw)
        except Exception as e:
            logger.debug("PubPeer failed for %s: %s", doi, e)
        return info

    # -- risk calculation --------------------------------------------------

    @staticmethod
    def _calculate_risk(result: RetractionResult) -> tuple[RiskLevel, list[str]]:
        factors: list[str] = []
        if result.has_retraction:
            factors.append("Paper has been RETRACTED by publisher")
            return RiskLevel.CRITICAL, factors
        if result.is_retracted_openalex:
            factors.append("Marked as retracted in OpenAlex")
            return RiskLevel.CRITICAL, factors
        for u in result.crossref_updates:
            if u.type in ("retraction", "withdrawal", "removal"):
                factors.append(f"Crossref update: {u.type}")
                return RiskLevel.CRITICAL, factors
            if u.type == "expression-of-concern":
                factors.append("Expression of Concern published")
        if result.has_concern:
            factors.append("Expression of Concern issued")
            return RiskLevel.HIGH, factors
        pp = result.pubpeer_info
        if pp and pp.comment_count >= 5:
            factors.append(f"Multiple PubPeer comments ({pp.comment_count})")
            if pp.concerns:
                factors.append(f"Concerns: {', '.join(pp.concerns[:3])}")
            return RiskLevel.HIGH, factors
        if result.has_correction:
            factors.append("Paper has been corrected")
        if pp and pp.comment_count >= 2:
            factors.append(f"PubPeer activity ({pp.comment_count} comments)")
            return RiskLevel.MEDIUM, factors
        if pp and pp.comment_count >= 1:
            factors.append("Some PubPeer discussion")
            return RiskLevel.LOW, factors
        return RiskLevel.NONE, factors

    # -- single DOI scan ---------------------------------------------------

    def scan_doi(self, doi: str) -> RetractionResult:
        result = RetractionResult(doi=doi, status="UNKNOWN")
        sources: list[str] = []

        # 1. Crossref
        updates, cr_meta = self._check_crossref(doi)
        sources.append("crossref")
        if updates:
            result.crossref_updates = updates
            for u in updates:
                if u.type in ("retraction", "withdrawal", "removal"):
                    result.has_retraction = True
                elif u.type == "expression-of-concern":
                    result.has_concern = True
                elif u.type in ("correction", "erratum", "corrigendum"):
                    result.has_correction = True
        if cr_meta:
            result.title = (cr_meta.get("title") or [""])[0] or None
            result.journal = (cr_meta.get("container-title") or [""])[0] or None
            result.authors = [f"{a.get('family', '')} {a.get('given', '')}".strip() for a in cr_meta.get("author", [])[:5]]
            for k in ("published-print", "published-online"):
                if k in cr_meta:
                    yp = cr_meta[k].get("date-parts", [[None]])
                    if yp and yp[0]:
                        result.publication_year = yp[0][0]
                        break

        # 2. OpenAlex
        is_ret, oa_data = self._check_openalex(doi)
        sources.append("openalex")
        result.is_retracted_openalex = is_ret
        if oa_data:
            result.openalex_id = oa_data.get("id")
            if not result.title:
                result.title = oa_data.get("display_name")
            if not result.publication_year:
                result.publication_year = oa_data.get("publication_year")

        # 3. PubPeer
        pp = self._check_pubpeer(doi)
        sources.append("pubpeer")
        result.pubpeer_info = pp
        result.pubpeer_comments = pp.comment_count
        result.pubpeer_url = pp.url

        # 4. Risk
        risk, factors = self._calculate_risk(result)
        result.risk_level_enum = risk
        result.risk_factors = factors
        result.sources_checked = sources

        # backward-compat risk_level string
        result.risk_level = risk.value

        # status
        if result.has_retraction or result.is_retracted_openalex:
            result.status = "RETRACTED"
        elif result.has_concern:
            result.status = "CONCERN"
        elif result.has_correction:
            result.status = "CORRECTED"
        elif result.title:
            result.status = "ACTIVE"
        else:
            result.status = "UNKNOWN"

        return result

    # -- batch scan --------------------------------------------------------

    def scan(self, text: str) -> list[RetractionResult]:
        dois = self.extract_doi(text)
        if not dois:
            return [RetractionResult(doi="N/A", status="NO_DOI_FOUND")]

        out: list[RetractionResult] = []
        for doi in dois:
            try:
                out.append(self.scan_doi(doi))
            except Exception as e:
                logger.error("Error scanning DOI %s: %s", doi, e)
                out.append(RetractionResult(doi=doi, status="ERROR", risk_factors=[str(e)]))
        return out

    def get_summary(self, results: list[RetractionResult]) -> dict[str, Any]:
        if not results:
            return {"total": 0}
        return {
            "total": len(results),
            "retracted": sum(1 for r in results if r.status == "RETRACTED"),
            "concerns": sum(1 for r in results if r.status == "CONCERN"),
            "corrected": sum(1 for r in results if r.status == "CORRECTED"),
            "active": sum(1 for r in results if r.status == "ACTIVE"),
            "unknown": sum(1 for r in results if r.status in ("UNKNOWN", "ERROR")),
            "critical_risk": sum(1 for r in results if r.risk_level_enum == RiskLevel.CRITICAL),
            "high_risk": sum(1 for r in results if r.risk_level_enum == RiskLevel.HIGH),
            "pubpeer_discussions": sum(1 for r in results if r.pubpeer_info and r.pubpeer_info.has_comments),
        }

    def close(self) -> None:
        if self._http_client:
            self._http_client.close()
            self._http_client = None

    def __del__(self) -> None:
        self.close()


# Singleton
retraction_scanner = RetractionScanner()
