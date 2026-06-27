from __future__ import annotations

import re
import unicodedata
from typing import Any

from .models import ReferenceMetadata
from .normalize import normalize_doi, normalize_author_name


_DOI_PATTERN = re.compile(r"(10\.\d{4,9}/[^\s]+)", re.IGNORECASE)
_PMID_PATTERNS = [
    re.compile(r"https?://pubmed\.ncbi\.nlm\.nih\.gov/\d{4,10}/?", re.IGNORECASE),
    re.compile(r"\bPMID\s*[:=]?\s*\d{4,10}\b", re.IGNORECASE),
]
_PMCID_PATTERNS = [
    re.compile(r"https?://(?:www\.)?ncbi\.nlm\.nih\.gov/pmc/articles/PMC\d+/?", re.IGNORECASE),
    re.compile(r"\bPMCID\s*[:=]?\s*PMC\d+\b", re.IGNORECASE),
]
_OPENALEX_PATTERNS = [
    re.compile(r"https?://(?:api\.)?openalex\.org/(?:works/)?W\d{6,}/?", re.IGNORECASE),
    re.compile(r"\bopenalex\s*:\s*W\d{6,}\b", re.IGNORECASE),
    re.compile(r"\bW\d{6,}\b"),
]
_NUMBERED_REFERENCE_MARKER_RE = re.compile(r"^\s*(?P<number>\d+)[.)]\s+(?=\S)")
_BRACKET_REFERENCE_MARKER_RE = re.compile(r"^\s*\[(?P<number>\d+)\]\s+(?=\S)")
_BULLET_REFERENCE_MARKER_RE = re.compile(r"^\s*(?P<bullet>[-*•])\s+(?=\S)")
_URL_PATTERN = re.compile(r"(?P<url>(?:https?://|www\.)[^\s<>\"]+)", re.IGNORECASE)
_REFERENCE_PREAMBLE_PATTERNS = (
    re.compile(r"^(?:references?|bibliography|citations?|citation\s+list)\s*$"),
    re.compile(r"^(?:please\s+verify|please\s+check|check\s+these\s+references?)\s*$"),
    re.compile(r"^(?:danh\s+sach\s+trich\s+dan|tai\s+lieu\s+tham\s+khao)\s*$"),
    re.compile(r"^(?:kiem\s+tra\s+cac\s+bai\s+sau|cac\s+nguon\s+sau)\s*$"),
)


def extract_authors(author_part: str) -> list[str]:
    if not author_part:
        return []

    author_part = re.sub(r"^\s*(?:\[\d+\]|\d+\.?)\s*", "", author_part)
    author_part = re.sub(r"\b(et\s+al\.?)\b.*", "", author_part, flags=re.IGNORECASE)

    apa_matches = re.findall(r"([A-Z][a-zA-Z\-']+),\s*[A-Z]\.", author_part)
    if apa_matches:
        return [normalize_author_name(name) for name in apa_matches if name.strip()]

    ieee_matches = re.findall(r"(?:[A-Z]\.\s*)+([A-Z][a-zA-Z\-']+)", author_part)
    if ieee_matches:
        return [normalize_author_name(name) for name in ieee_matches if name.strip()]

    parts = re.split(r",|\b(?:and|&)\b", author_part)
    results: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        cleaned = re.sub(r"\b(?:[A-Z]\b\.?\s*)+", "", part)
        cleaned = re.sub(r"\b[A-Z]{1,2}\b", "", cleaned).strip()
        words = cleaned.split() or part.split()
        if words:
            results.append(normalize_author_name(words[-1]))
    return [value for value in results if value]


def parse_reference_metadata(raw: str) -> ReferenceMetadata:
    raw_clean = re.sub(r"\s+", " ", (raw or "").strip())

    doi = None
    doi_match = _DOI_PATTERN.search(raw_clean)
    if doi_match:
        doi = normalize_doi(doi_match.group(1))

    year = None
    years = [int(item) for item in re.findall(r"\b(19\d{2}|20[0-2]\d)\b", raw_clean)]
    parentheses_year_match = re.search(r"\(\s*(19\d{2}|20[0-2]\d)\s*\)", raw_clean)
    if parentheses_year_match:
        year = int(parentheses_year_match.group(1))
    elif years:
        year = years[-1]

    title = None
    authors: list[str] = []
    venue = None
    volume = None
    issue = None
    pages = None

    vol_issue_match = re.search(r"\b(\d+)\((\d+)\)", raw_clean)
    if vol_issue_match:
        volume = vol_issue_match.group(1)
        issue = vol_issue_match.group(2)
    else:
        vol_match = re.search(r"\b(?:vol\.|volume)\s*(\d+)\b", raw_clean, re.IGNORECASE)
        issue_match = re.search(r"\b(?:no\.|number|issue)\s*(\d+)\b", raw_clean, re.IGNORECASE)
        if vol_match:
            volume = vol_match.group(1)
        if issue_match:
            issue = issue_match.group(1)

    pages_match = re.search(r"\bpp\.\s*([a-zA-Z0-9]+[-–][a-zA-Z0-9]+|[a-zA-Z0-9]+)\b", raw_clean, re.IGNORECASE)
    if not pages_match:
        pages_match = re.search(r"\bpages\s*([a-zA-Z0-9]+[-–][a-zA-Z0-9]+|[a-zA-Z0-9]+)\b", raw_clean, re.IGNORECASE)
    if not pages_match:
        pages_match = re.search(r"\b([0-9]+[-–][0-9]+)\b", raw_clean)
    if pages_match:
        pages = pages_match.group(1)

    quotes_match = re.search(r'["“]([^"”]+)["”]', raw_clean)
    if quotes_match:
        title = quotes_match.group(1).strip()
        idx = raw_clean.find(quotes_match.group(0))
        author_part = raw_clean[:idx].strip()
        authors = extract_authors(author_part)

        rest = raw_clean[idx + len(quotes_match.group(0)):].strip()
        rest_parts = [part.strip() for part in rest.split(",") if part.strip()]
        venue_candidates = []
        for part in rest_parts:
            lowered = part.lower()
            if not any(word in lowered for word in ["vol.", "volume", "no.", "number", "issue", "pp.", "pages"]) and not re.search(r"\b(19\d{2}|20\d{2})\b", part):
                venue_candidates.append(part)
        if venue_candidates:
            venue = venue_candidates[0].strip()
    elif parentheses_year_match:
        idx_start = parentheses_year_match.start()
        idx_end = parentheses_year_match.end()
        author_part = raw_clean[:idx_start].strip()
        authors = extract_authors(author_part)
        rest = re.sub(r"^[.\s,;:–\-]+", "", raw_clean[idx_end:].strip())
        rest_sentences = [sentence.strip() for sentence in rest.split(". ") if sentence.strip()]
        if rest_sentences:
            title = rest_sentences[0].strip()
            if len(rest_sentences) > 1:
                venue_candidate = rest_sentences[1].strip()
                venue = re.split(r",|\bvol\b|\bvolume\b", venue_candidate, flags=re.IGNORECASE)[0].strip()
                if not volume or not issue or not pages:
                    vol_issue = re.search(r"\b(\d+)\((\d+)\)", venue_candidate)
                    if vol_issue:
                        volume = volume or vol_issue.group(1)
                        issue = issue or vol_issue.group(2)
                    if not pages:
                        page_match = re.search(r"\b(?:pp\.|pages)\s*([a-zA-Z0-9]+[-–][a-zA-Z0-9]+|[a-zA-Z0-9]+)\b", venue_candidate, re.IGNORECASE)
                        if not page_match:
                            page_match = re.search(r"\b([0-9]+[-–][0-9]+)\b", venue_candidate)
                        if page_match:
                            pages = page_match.group(1)
                    if not volume and venue:
                        temp = venue_candidate[len(venue):].strip()
                        if pages:
                            temp = temp.replace(pages, "")
                        vol_candidate = re.search(r"\b(\d+)\b", temp)
                        if vol_candidate:
                            volume = vol_candidate.group(1)
    else:
        cleaned_raw = re.sub(r"^\s*(?:\[\d+\]|\d+\.?)\s*", "", raw_clean)
        parts = re.split(r"(?<=\.)\s+(?=[A-Z][a-zA-Z]{1,})", cleaned_raw)
        if len(parts) >= 3:
            authors = extract_authors(parts[0])
            title = parts[1].strip()
            venue_candidate = parts[2].strip()
            venue = re.split(r",|\bvol\b|\bvolume\b", venue_candidate, flags=re.IGNORECASE)[0].strip()
            if not volume or not issue or not pages:
                vol_issue = re.search(r"\b(\d+)\((\d+)\)", venue_candidate)
                if vol_issue:
                    volume = volume or vol_issue.group(1)
                    issue = issue or vol_issue.group(2)
                if not pages:
                    page_match = re.search(r"\b(?:pp\.|pages)\s*([a-zA-Z0-9]+[-–][a-zA-Z0-9]+|[a-zA-Z0-9]+)\b", venue_candidate, re.IGNORECASE)
                    if not page_match:
                        page_match = re.search(r"\b([0-9]+[-–][0-9]+)\b", venue_candidate)
                    if page_match:
                        pages = page_match.group(1)
                if not volume and venue:
                    temp = venue_candidate[len(venue):].strip()
                    if pages:
                        temp = temp.replace(pages, "")
                    vol_candidate = re.search(r"\b(\d+)\b", temp)
                    if vol_candidate:
                        volume = vol_candidate.group(1)
        elif len(parts) == 2:
            authors = extract_authors(parts[0])
            title = parts[1].strip()
        else:
            title = cleaned_raw

    if title:
        title = re.sub(r'^[“"‘\'\s\[({,]+|[.”"’\'\s\])},;:]+$', "", title).strip()
    if venue:
        venue = re.sub(r'^[“"‘\'\s\[({,]+|[.”"’\'\s\])},;:]+$', "", venue).strip()

    confidence = 0.05
    if not title:
        if authors and year:
            confidence = 0.35
        elif year:
            confidence = 0.20
    else:
        if year:
            confidence = 0.85 if authors else 0.65
        else:
            confidence = 0.50 if authors else 0.30

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
        confidence=confidence,
    )


def build_fallback_title_query(raw: str, parsed: ReferenceMetadata) -> str | None:
    if parsed.title:
        significant_words = re.findall(r"[A-Za-z]{4,}", parsed.title)
        if len(significant_words) >= 4:
            return parsed.title.strip()

    cleaned = raw or ""
    cleaned = _DOI_PATTERN.sub(" ", cleaned)
    for pattern in _PMID_PATTERNS + _PMCID_PATTERNS + _OPENALEX_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"\b(19\d{2}|20[0-2]\d)\b", " ", cleaned)
    cleaned = re.sub(r"[^A-Za-z\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None

    tokens = [token for token in cleaned.split() if len(token) >= 4]
    if len(tokens) < 4:
        return None
    return " ".join(tokens[:18]).strip()


def _ascii_fold_text(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "")
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text).strip().lower()


def is_reference_preamble_line(text: str) -> bool:
    normalized = _ascii_fold_text(str(text or "")).rstrip(":").strip()
    if not normalized:
        return True
    if any(pattern.match(normalized) for pattern in _REFERENCE_PREAMBLE_PATTERNS):
        return True
    return str(text or "").strip().endswith(":") and len(normalized.split()) <= 8


def _match_reference_marker(text: str) -> tuple[int | None, str] | None:
    for pattern in (_BRACKET_REFERENCE_MARKER_RE, _NUMBERED_REFERENCE_MARKER_RE):
        match = pattern.match(text)
        if match:
            number = match.groupdict().get("number")
            source_number = int(number) if number is not None else None
            return source_number, text[match.end():].strip()

    bullet_match = _BULLET_REFERENCE_MARKER_RE.match(text)
    if bullet_match:
        return None, text[bullet_match.end():].strip()

    return None


def extract_first_url(text: str) -> str | None:
    match = _URL_PATTERN.search(text or "")
    if not match:
        return None
    url = match.group("url").strip().rstrip(".,;:")
    while url.endswith(")") and url.count("(") < url.count(")"):
        url = url[:-1]
    return url or None


def extract_reference_items(text: str) -> list[dict[str, Any]]:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return []

    lines = normalized.split("\n")
    items: list[dict[str, Any]] = []
    current_lines: list[str] = []
    current_source_number: int | None = None
    current_explicit_marker = False
    saw_explicit_marker = False

    def flush_current() -> None:
        nonlocal current_lines, current_source_number, current_explicit_marker
        if not current_lines:
            return
        raw_item = "\n".join(line.rstrip() for line in current_lines if line.strip()).strip()
        if raw_item and not is_reference_preamble_line(raw_item):
            items.append(
                {
                    "raw": raw_item,
                    "source_number": current_source_number,
                    "explicit_marker": current_explicit_marker,
                }
            )
        current_lines = []
        current_source_number = None
        current_explicit_marker = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if saw_explicit_marker:
                flush_current()
            continue

        marker = _match_reference_marker(stripped)
        if marker is not None:
            saw_explicit_marker = True
            flush_current()
            current_source_number, marker_text = marker
            current_explicit_marker = True
            if marker_text:
                current_lines = [marker_text]
            continue

        if not current_lines and is_reference_preamble_line(stripped):
            continue

        if current_lines:
            current_lines.append(stripped)
        else:
            current_lines = [stripped]
            current_source_number = None
            current_explicit_marker = False

    flush_current()
    return items
