from __future__ import annotations

import re
from typing import Any

from .models import CandidateWork
from .normalize import normalize_author_for_citation, normalize_author_name, normalize_title


def _format_apa_authors(authors: list[str]) -> str:
    formatted = [normalize_author_for_citation(author) for author in authors if author]
    formatted = [author for author in formatted if author]
    if not formatted:
        return ""
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} & {formatted[1]}"
    return f"{', '.join(formatted[:-1])}, & {formatted[-1]}"


def infer_item_type(metadata: dict[str, Any]) -> str:
    raw_type = str(metadata.get("raw_type") or metadata.get("type") or "").lower()
    venue = str(metadata.get("venue") or "").lower()
    publication_types = metadata.get("publication_types") or []
    if isinstance(publication_types, str):
        publication_types = [publication_types]
    publication_type_text = " ".join(str(item).lower() for item in publication_types)

    combined = f"{raw_type} {venue} {publication_type_text}"
    if any(token in combined for token in ("proceeding", "conference", "symposium", "workshop")):
        return "inproceedings"
    if any(token in combined for token in ("journal", "article", "scholarlyarticle")):
        return "article"
    if metadata.get("volume") or metadata.get("issue"):
        return "article"
    return "misc"


def build_completed_metadata(
    candidate: CandidateWork,
    confidence: float,
    source: str | None = None,
) -> dict[str, Any]:
    if not candidate:
        return {}

    raw = candidate.raw or {}
    publication_types = raw.get("publicationTypes") or raw.get("types")
    metadata: dict[str, Any] = {}
    for key, value in (
        ("source", source or candidate.source),
        ("confidence", round(confidence, 3)),
        ("title", candidate.title),
        ("authors", list(candidate.authors or [])),
        ("year", candidate.year),
        ("venue", candidate.venue),
        ("doi", candidate.doi),
        ("url", candidate.resolved_url or candidate.url),
        ("external_id", candidate.external_id),
        ("external_id_type", candidate.external_id_type),
        ("volume", candidate.volume),
        ("issue", candidate.issue),
        ("pages", candidate.pages),
        ("publication_types", publication_types),
        ("raw_type", raw.get("type") or raw.get("types", {}).get("schemaOrg") if isinstance(raw.get("types"), dict) else None),
    ):
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        metadata[key] = value

    metadata["type"] = infer_item_type(metadata)
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
    if not metadata:
        return ""

    authors = metadata.get("authors") or []
    if not isinstance(authors, list):
        authors = []
    author_text = _format_apa_authors([str(author) for author in authors])
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
    return value.replace("\\", "\\textbackslash{}").replace("{", "\\{").replace("}", "\\}")


def _bibtex_key(metadata: dict[str, Any]) -> str:
    authors = metadata.get("authors") or []
    first_author = ""
    if isinstance(authors, list) and authors:
        normalized = normalize_author_name(str(authors[0])).split()
        if normalized:
            first_author = normalized[-1]

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
        author_text = " and ".join(normalize_author_for_citation(str(author)) for author in authors if author)
        add("author", author_text)
    add("year", metadata.get("year"))
    venue_field = "booktitle" if item_type == "inproceedings" else "journal"
    add(venue_field, metadata.get("venue"))
    add("volume", metadata.get("volume"))
    add("number", metadata.get("issue"))
    add("pages", metadata.get("pages"))
    add("doi", metadata.get("doi"))
    add("url", metadata.get("url"))

    body = "\n".join(f"  {name} = {{{_bibtex_escape(str(value))}}}," for name, value in fields)
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
        csl_authors = [_csl_author(str(author)) for author in authors]
        csl_authors = [author for author in csl_authors if author]
        if csl_authors:
            csl["author"] = csl_authors

    year = metadata.get("year")
    if year:
        csl["issued"] = {"date-parts": [[year]]}

    return csl
