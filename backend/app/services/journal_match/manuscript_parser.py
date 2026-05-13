from __future__ import annotations

import re
from collections import Counter
from typing import Any


class ManuscriptParser:
    ABSTRACT_PATTERN = re.compile(
        r"(?is)\babstract\b[:\s]*(.+?)(?=\n\s*(keywords?|index terms|introduction|background|1[\.\s]))"
    )
    KEYWORD_PATTERN = re.compile(r"(?im)^\s*(keywords?|index terms)\s*[:\-]\s*(.+)$")
    REFERENCE_PATTERN = re.compile(r"(?is)\b(references|bibliography)\b(.*)$")
    SECTION_PATTERN = re.compile(r"(?m)^\s*(?:\d+(?:\.\d+)*)?\.?\s*([A-Z][A-Za-z][A-Za-z \-/]{2,})\s*$")

    def _clean(self, text: str | None) -> str:
        return re.sub(r"\s+", " ", (text or "").strip())

    def _split_lines(self, text: str) -> list[str]:
        return [line.strip() for line in text.splitlines() if line.strip()]

    def extract_title(self, text: str, explicit_title: str | None = None) -> str | None:
        if explicit_title and explicit_title.strip():
            return self._clean(explicit_title)
        lines = self._split_lines(text[:1200])
        if not lines:
            return None
        first = lines[0]
        if len(first.split()) <= 30:
            return self._clean(first)
        return None

    def extract_abstract(self, text: str, title: str | None) -> str | None:
        match = self.ABSTRACT_PATTERN.search(text)
        if match:
            return self._clean(match.group(1))
        body = text
        if title:
            body = body.replace(title, "", 1)
        paragraphs = [self._clean(chunk) for chunk in re.split(r"\n\s*\n", body) if self._clean(chunk)]
        return paragraphs[0][:2500] if paragraphs else None

    def extract_keywords(self, text: str, abstract: str | None) -> list[str]:
        match = self.KEYWORD_PATTERN.search(text)
        if match:
            return [part.strip() for part in re.split(r"[;,]", match.group(2)) if part.strip()]
        corpus = self._clean((abstract or "") + " " + text[:2000]).lower()
        stopwords = {
            "the", "and", "for", "with", "from", "that", "this", "using", "based", "study",
            "analysis", "approach", "paper", "results", "method", "methods", "towards",
        }
        tokens = [token for token in re.findall(r"[a-z][a-z\-]{3,}", corpus) if token not in stopwords]
        common = [token for token, _ in Counter(tokens).most_common(6)]
        return common[:5]

    def extract_references(self, text: str) -> list[dict[str, Any]]:
        match = self.REFERENCE_PATTERN.search(text)
        if not match:
            return []
        section = match.group(2).strip()
        raw_lines = [line.strip() for line in section.splitlines() if line.strip()]
        references: list[dict[str, Any]] = []
        buffer = ""
        for line in raw_lines:
            if re.match(r"^(\[\d+\]|\d+\.)\s+", line) and buffer:
                references.append(self._reference_item(buffer))
                buffer = line
            else:
                buffer = f"{buffer} {line}".strip()
        if buffer:
            references.append(self._reference_item(buffer))
        return references[:50]

    def _reference_item(self, text: str) -> dict[str, Any]:
        doi_match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", text, re.IGNORECASE)
        return {"raw": self._clean(text), "doi": doi_match.group(0).lower() if doi_match else None}

    def extract_sections(self, text: str) -> list[str]:
        sections = []
        seen: set[str] = set()
        for match in self.SECTION_PATTERN.finditer(text):
            label = self._clean(match.group(1))
            key = label.lower()
            if label and key not in seen and len(label.split()) <= 8:
                seen.add(key)
                sections.append(label)
        return sections[:20]

    def parse(self, text: str, title: str | None = None) -> dict[str, Any]:
        clean_text = text.strip()
        parsed_title = self.extract_title(clean_text, explicit_title=title)
        abstract = self.extract_abstract(clean_text, parsed_title)
        keywords = self.extract_keywords(clean_text, abstract)
        references = self.extract_references(clean_text)
        sections = self.extract_sections(clean_text)
        return {
            "title": parsed_title,
            "abstract": abstract,
            "keywords": keywords,
            "references": references,
            "structure": {"sections": sections},
            "body_text": clean_text,
        }

    def assess(self, parsed: dict[str, Any]) -> dict[str, Any]:
        title_present = bool(parsed.get("title"))
        abstract_present = bool(parsed.get("abstract"))
        keyword_count = len(parsed.get("keywords") or [])
        reference_count = len(parsed.get("references") or [])
        word_count = len((parsed.get("body_text") or "").split())
        warnings: list[str] = []
        if not title_present:
            warnings.append("Title could not be confidently extracted.")
        if not abstract_present:
            warnings.append("Abstract section is missing or weakly detected.")
        if keyword_count < 3:
            warnings.append("Manuscript has fewer than three strong keywords.")
        if reference_count < 5:
            warnings.append("Reference section looks sparse for robust matching.")
        readiness = (
            (0.25 if title_present else 0.0)
            + (0.25 if abstract_present else 0.0)
            + min(keyword_count / 5.0, 1.0) * 0.15
            + min(reference_count / 10.0, 1.0) * 0.15
            + min(word_count / 3000.0, 1.0) * 0.20
        )
        return {
            "readiness_score": round(readiness, 4),
            "title_present": title_present,
            "abstract_present": abstract_present,
            "keyword_count": keyword_count,
            "reference_count": reference_count,
            "estimated_word_count": word_count,
            "warnings": warnings,
        }


manuscript_parser = ManuscriptParser()
