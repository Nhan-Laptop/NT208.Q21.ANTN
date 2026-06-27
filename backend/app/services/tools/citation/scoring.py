from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from .models import CandidateWork, MetadataMatchResult, ReferenceMetadata
from .normalize import normalize_author_name, normalize_title, normalize_venue, safe_float


MATCH_WEIGHTS = {
    "title": 0.55,
    "authors": 0.20,
    "year": 0.10,
    "venue": 0.10,
    "volume_issue_pages": 0.05,
}
SOURCE_ERROR_STATES = {"timeout", "http_error", "error", "rate_limited"}
TITLE_MATCH_THRESHOLD = 0.75
TITLE_STRONG_THRESHOLD = 0.90
AUTHOR_MATCH_THRESHOLD = 0.80
AUTHOR_PARTIAL_THRESHOLD = 0.50
VENUE_MATCH_THRESHOLD = 0.80
VENUE_PARTIAL_THRESHOLD = 0.50
LOW_PARSE_CONFIDENCE = 0.40


def candidate_missing_fields(ref: ReferenceMetadata, candidate: CandidateWork) -> list[str]:
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


def build_match_reason(
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
            if isinstance(diag, dict) and diag.get("state") in SOURCE_ERROR_STATES
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

    title_verdict = ((evidence.get("title") or {}).get("verdict"))
    if title_verdict == "match":
        positive.append("title matches strongly")
    elif title_verdict == "partial_match":
        caution.append("title is only partially similar")
    elif title_verdict == "mismatch":
        caution.append("title differs")

    author_verdict = ((evidence.get("authors") or {}).get("verdict"))
    if author_verdict == "match":
        positive.append("authors align well")
    elif author_verdict == "partial_match":
        positive.append("authors partially align")
    elif author_verdict == "mismatch":
        caution.append("authors differ")

    year_verdict = ((evidence.get("year") or {}).get("verdict"))
    if year_verdict == "exact":
        positive.append("year matches exactly")
    elif year_verdict == "near_match":
        positive.append("year is close")
    elif year_verdict == "mismatch":
        caution.append("year differs")

    venue_verdict = ((evidence.get("venue") or {}).get("verdict"))
    if venue_verdict == "match":
        positive.append("venue matches")
    elif venue_verdict == "partial_match":
        positive.append("venue is partially aligned")
    elif venue_verdict == "mismatch":
        caution.append("venue differs")

    vol_verdict = ((evidence.get("volume_issue_pages") or {}).get("verdict"))
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


def compare_reference_to_candidate(ref: ReferenceMetadata, candidate: CandidateWork) -> dict[str, Any]:
    title_similarity = None
    title_verdict = "not_provided"
    if ref.title:
        if candidate.title:
            ref_title_norm = normalize_title(ref.title)
            cand_title_norm = normalize_title(candidate.title)
            title_similarity = SequenceMatcher(None, ref_title_norm, cand_title_norm).ratio()
            if title_similarity >= TITLE_STRONG_THRESHOLD:
                title_verdict = "match"
            elif title_similarity >= TITLE_MATCH_THRESHOLD:
                title_verdict = "partial_match"
            else:
                title_verdict = "mismatch"
        else:
            title_verdict = "missing_candidate"

    author_overlap = None
    author_verdict = "not_provided"
    ref_authors_norm = [normalize_author_name(author) for author in ref.authors if author]
    cand_authors_norm = [normalize_author_name(author) for author in candidate.authors if author]
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
            if author_overlap >= AUTHOR_MATCH_THRESHOLD:
                author_verdict = "match"
            elif author_overlap >= AUTHOR_PARTIAL_THRESHOLD:
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
            if venue_similarity >= VENUE_MATCH_THRESHOLD:
                venue_verdict = "match"
            elif venue_similarity >= VENUE_PARTIAL_THRESHOLD:
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
        "title": {"input": ref.title, "candidate": candidate.title, "similarity": safe_float(title_similarity), "verdict": title_verdict},
        "authors": {"input": list(ref.authors or []), "candidate": list(candidate.authors or []), "similarity": safe_float(author_overlap), "verdict": author_verdict},
        "year": {"input": ref.year, "candidate": candidate.year, "similarity": safe_float(year_score), "verdict": year_verdict},
        "venue": {"input": ref.venue, "candidate": candidate.venue, "similarity": safe_float(venue_similarity), "verdict": venue_verdict},
        "volume_issue_pages": {
            "input": {"volume": ref.volume, "issue": ref.issue, "pages": ref.pages},
            "candidate": {"volume": candidate.volume, "issue": candidate.issue, "pages": candidate.pages},
            "similarity": safe_float(volume_issue_pages_score),
            "verdict": volume_issue_pages_verdict,
        },
        "doi": {
            "input": ref.doi,
            "candidate": candidate.doi,
            "similarity": None,
            "verdict": "exact" if ref.doi and candidate.doi and ref.doi == candidate.doi else ("source_backed" if candidate.doi else "missing_candidate"),
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
        weight = MATCH_WEIGHTS[field_name]
        available_weight += weight
        weighted_score += weight * similarity
        if field_name != "title":
            corroborating_comparable += 1
            if similarity >= 0.5:
                corroborating_strong += 1

    final_score = (weighted_score / available_weight) if available_weight > 0 else 0.0
    missing_fields = candidate_missing_fields(ref, candidate)
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


def score_candidate(ref: ReferenceMetadata, candidate: CandidateWork) -> dict[str, Any]:
    return compare_reference_to_candidate(ref, candidate)


def candidate_has_incomplete_metadata(ref: ReferenceMetadata, candidate: CandidateWork) -> bool:
    missing = candidate_missing_fields(ref, candidate)
    critical_missing = {"authors", "year"}
    return any(field in critical_missing for field in missing) or len(missing) >= 3


def top_source_candidate(candidates: list[CandidateWork], source: str) -> CandidateWork | None:
    for candidate in candidates:
        if candidate.source == source:
            return candidate
    return None


def has_source_conflict(ref: ReferenceMetadata, candidates: list[CandidateWork]) -> bool:
    crossref_candidate = top_source_candidate(candidates, "crossref")
    openalex_candidate = top_source_candidate(candidates, "openalex")
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


def metadata_consistency_from_field_evidence(field_evidence: dict[str, Any] | None) -> str:
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


def choose_best_match(ref: ReferenceMetadata, candidates: list[CandidateWork]) -> MetadataMatchResult:
    if not ref or ref.confidence <= LOW_PARSE_CONFIDENCE or not ref.title:
        return MetadataMatchResult(
            reference=ref,
            status="PARSE_FAILED",
            confidence=0.0,
            warning="Parsing failed or title is missing in reference metadata.",
            reason="Could not extract enough structured or title-like metadata to search scholarly sources.",
            parse_status="UNPARSABLE",
        )

    if not candidates:
        warning = None if ref.doi else "Warning: Citation does not contain DOI, matched via metadata search."
        return MetadataMatchResult(
            reference=ref,
            status="NO_MATCH_FOUND",
            confidence=0.0,
            warning=warning,
            reason="No scholarly source produced a plausible metadata candidate for this reference.",
        )

    scored_candidates: list[tuple[CandidateWork, dict[str, Any]]] = []
    for candidate in candidates:
        evidence = score_candidate(ref, candidate)
        scored_candidates.append((candidate, evidence))
    scored_candidates.sort(key=lambda item: item[1]["final_score"], reverse=True)

    top_3 = [item[0] for item in scored_candidates[:3]]
    top_3_details = [
        {
            "source": item[0].source,
            "title": item[0].title,
            "authors": list(item[0].authors or []),
            "year": item[0].year,
            "venue": item[0].venue,
            "doi": item[0].doi,
            "url": item[0].resolved_url or item[0].url,
            "external_id": item[0].external_id,
            "external_id_type": item[0].external_id_type,
            "score": item[1]["final_score"],
            "missing_fields": list(item[1].get("candidate_missing_fields") or []),
        }
        for item in scored_candidates[:3]
    ]
    best_candidate, best_evidence = scored_candidates[0]
    top1_score = best_evidence["final_score"]

    status = "UNVERIFIED_NO_DOI"
    if top1_score >= 0.90:
        status = "METADATA_VERIFIED"
    elif top1_score >= 0.80:
        status = "LIKELY_MATCH"
    elif top1_score >= 0.65:
        status = "POSSIBLE_MATCH"

    title_similarity = best_evidence.get("title_similarity", 0.0)
    title_verdict = ((best_evidence.get("field_evidence") or {}).get("title") or {}).get("verdict")
    if title_similarity < TITLE_MATCH_THRESHOLD or title_verdict == "mismatch":
        if status in {"METADATA_VERIFIED", "LIKELY_MATCH"}:
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

    candidate_gap = None
    if len(scored_candidates) > 1 and top1_score >= 0.65:
        top2_score = scored_candidates[1][1]["final_score"]
        candidate_gap = round(top1_score - top2_score, 3)
        if candidate_gap < 0.05:
            status = "AMBIGUOUS_MATCH"

    warning = None
    if not ref.doi:
        warning = "Warning: Citation does not contain DOI, matched via metadata search."
    if status in {"LIKELY_MATCH", "POSSIBLE_MATCH", "AMBIGUOUS_MATCH", "UNVERIFIED_NO_DOI"}:
        warning = "Candidate found, but confidence is not high enough to generate a verified formatted citation."

    resolver_chain = sorted({candidate.source for candidate in top_3 if candidate.source})
    evidence_urls: list[str] = []
    seen_urls: set[str] = set()
    for candidate in top_3:
        for url in [candidate.resolved_url, candidate.url, *(candidate.evidence_urls or [])]:
            if not url or url in seen_urls:
                continue
            evidence_urls.append(url)
            seen_urls.add(url)

    return MetadataMatchResult(
        reference=ref,
        status=status,
        confidence=top1_score,
        best_candidate=best_candidate,
        candidates=top_3,
        candidate_details=top_3_details,
        evidence=best_evidence,
        warning=warning,
        reason=build_match_reason(status, best_evidence.get("field_evidence")),
        field_evidence=best_evidence.get("field_evidence"),
        candidate_gap=candidate_gap,
        resolved_url=best_candidate.resolved_url or best_candidate.url or (f"https://doi.org/{best_candidate.doi}" if best_candidate.doi else None),
        evidence_urls=evidence_urls,
        resolver_chain=resolver_chain,
    )
