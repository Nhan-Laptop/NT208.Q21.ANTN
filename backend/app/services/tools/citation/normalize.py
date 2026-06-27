from __future__ import annotations

import re
from typing import Any


DOI_NORMALIZE_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", re.IGNORECASE)


def normalize_doi(raw: str) -> str:
    doi = (raw or "").strip()
    doi = DOI_NORMALIZE_RE.sub("", doi)
    doi = doi.strip(" \t\n\r<>{}[]\"'")
    doi = doi.rstrip(".,;:")
    while doi.endswith(")") and doi.count("(") < doi.count(")"):
        doi = doi[:-1]
    return doi.lower()


def normalize_title(title: str) -> str:
    if not title:
        return ""
    value = title.lower()
    value = re.sub(r'^[“"‘\'\s\[({]+|[.”"’\'\s\])},;:]+$', "", value)
    value = re.sub(r"[?:/]+", " ", value)
    value = re.sub(r"[-‐‑‒–—]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_author_name(name: str) -> str:
    if not name:
        return ""
    value = name.strip()
    value = re.sub(r"\b(et\s+al\.?|and|&)\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[,\.\-'\"]", " ", value)
    return value.lower().strip()


def _display_name_part(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.isupper() and len(value) <= 3:
        return value
    return "-".join(part.capitalize() for part in value.split("-") if part)


def normalize_author_for_citation(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", (name or "").strip())
    if not cleaned:
        return ""

    cleaned = re.sub(r"\b(et\s+al\.?|and|&)\b", "", cleaned, flags=re.IGNORECASE).strip(" ,;")
    if not cleaned:
        return ""

    if "," in cleaned:
        family, given = [part.strip() for part in cleaned.split(",", 1)]
        family_display = " ".join(_display_name_part(p) for p in family.split() if p)
        initials = [f"{part[0].upper()}." for part in re.split(r"[\s.-]+", given) if part]
        return f"{family_display}, {' '.join(initials)}" if initials else family_display

    parts = [part for part in re.split(r"\s+", cleaned) if part]
    if len(parts) == 1:
        return _display_name_part(parts[0])

    family = _display_name_part(parts[-1])
    initials = [f"{part[0].upper()}." for part in parts[:-1] if part]
    return f"{family}, {' '.join(initials)}" if initials else family


def normalize_venue(venue: str) -> str:
    if not venue:
        return ""
    value = venue.strip()
    value = re.sub(r'^[“"‘\'\s\[({]+|[.”"’\'\s\])},;:]+$', "", value)
    value = re.sub(r"^(the\s+)?journal\s+of\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(the\s+)?proceedings\s+of\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value


def safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def safe_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)
