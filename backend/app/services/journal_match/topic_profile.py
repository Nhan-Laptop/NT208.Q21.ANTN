from __future__ import annotations

import re
from collections import Counter
from typing import Any

APPLICATION_PATTERNS = re.compile(
    r"(we\s+(apply|implement|evaluate|test|validate)"
    r"|we\s+use\s+\w+\s+to"
    r"|application\s+in|applications?\s+include|example|such\s+as|for\s+example"
    r"|case\s+study|in\s+the\s+context\s+of"
    r"|as\s+(an\s+)?(application\s+)?example"
    r"|as\s+a\s+(practical\s+)?(use\s+)?(case|application|demonstration)"
    r"|to\s+illustrate|we\s+illustrate)",
    re.IGNORECASE,
)

FIELD_KEYWORDS: dict[str, set[str]] = {
    "computer_science": {
        "algorithm", "computation", "computing", "data", "database", "machine learning",
        "neural", "network", "programming", "software", "system", "python", "numpy",
        "java", "c++", "api", "library", "framework", "binary", "code", "compiler",
    },
    "scientific_computing": {
        "numerical", "simulation", "scientific computing", "high-performance", "hpc",
        "matlab", "julia", "r-project", "computational", "modelling", "modeling",
        "array", "matrix", "linear algebra", "fft", "floating-point",
    },
    "mathematics": {
        "algebra", "calculus", "differential", "equation", "geometry", "graph theory",
        "linear", "optimization", "probability", "statistics", "theorem", "proof",
        "topology", "discrete", "combinatorial",
    },
    "physics_astronomy": {
        "astronomy", "astrophysics", "cosmology", "galaxy", "gravitational", "particle",
        "quantum", "relativity", "spectroscopy", "telescope", "black hole", "star",
        "planet", "stellar", "nuclear",
    },
    "biology_medicine": {
        "biology", "clinical", "disease", "dna", "gene", "genetic", "genome", "medical",
        "medicine", "patient", "protein", "cell", "molecular", "biochemistry",
    },
    "engineering": {
        "circuit", "control", "electrical", "mechanical", "robot", "signal", "structural",
        "thermal", "aerospace", "automotive", "embedded",
    },
    "social_sciences": {
        "anthropology", "community", "cultural", "demographic", "economic", "ethnographic",
        "geography", "political", "psychology", "social", "sociology", "qualitative",
        "survey", "interview", "urban",
    },
    "food_studies": {
        "cuisine", "culinary", "food", "gastronomy", "nutrition", "street food",
        "cooking", "fermentation", "recipe", "diet", "beverage",
    },
    "environmental_sciences": {
        "climate", "conservation", "ecological", "ecology", "environment", "sustainability",
        "biodiversity", "ecosystem", "pollution", "renewable",
    },
}


class ManuscriptTopicProfile:
    def __init__(
        self,
        title: str | None = None,
        abstract: str | None = None,
        keywords: list[str] | None = None,
        subjects: list[str] | None = None,
        body_text: str | None = None,
    ):
        self.title = (title or "").strip()
        self.abstract = (abstract or "").strip()
        self.keywords = keywords or []
        self.subjects = subjects or []
        self.body_text = (body_text or "").strip()
        self._analyze()

    def _tokenize(self, text: str) -> set[str]:
        return {t.lower() for t in re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", text)}

    def _sentences(self, text: str) -> list[str]:
        return [s.strip() for s in re.split(r"[.?!]\s+", text) if len(s.strip()) > 20]

    def _classify_field(self) -> str | None:
        all_text = " ".join([
            self.title,
            self.abstract,
            " ".join(self.keywords),
            " ".join(self.subjects),
        ]).lower()
        scores: dict[str, int] = {}
        for field, terms in FIELD_KEYWORDS.items():
            score = sum(1 for term in terms if term.lower() in all_text)
            if score > 0:
                scores[field] = score
        if not scores:
            return None
        return max(scores, key=scores.get)

    def _extract_main_topic(self) -> str:
        parts: list[str] = []
        if self.title:
            parts.append(self.title)
        if self.keywords:
            parts.append("Keywords: " + ", ".join(self.keywords[:8]))
        if self.subjects:
            parts.append("Subjects: " + ", ".join(self.subjects[:6]))
        first_sentences = self._sentences(self.abstract)
        if first_sentences:
            parts.append(first_sentences[0][:300])
        return "\n".join(parts)

    def _extract_application_domain(self) -> str:
        app_sentences: list[str] = []
        for sentence in self._sentences(self.abstract):
            if APPLICATION_PATTERNS.search(sentence):
                app_sentences.append(sentence)
        return " ".join(app_sentences[:3])

    def _find_excluded_minor_topics(self) -> list[str]:
        main_tokens = self._tokenize(self._extract_main_topic())
        app_text = self._extract_application_domain()
        if not app_text:
            return []
        app_tokens = self._tokenize(app_text)
        excluded = app_tokens - main_tokens
        stopwords = {
            "the", "and", "for", "with", "from", "that", "this", "using", "based",
            "study", "analysis", "approach", "paper", "results", "method", "methods",
            "example", "also", "show", "shown", "demonstrate", "demonstrates",
            "application", "applications", "include", "includes",
        }
        return sorted(t for t in excluded if t not in stopwords)[:10]

    def _analyze(self) -> None:
        self.research_field = self._classify_field()
        self.main_topic_text = self._extract_main_topic()
        self.application_domain_text = self._extract_application_domain()
        self.excluded_minor_topics = self._find_excluded_minor_topics()
        main_sentences = self._sentences(self.abstract) if self._sentences(self.abstract) else [""]
        abstract_without_app = []
        for sentence in self._sentences(self.abstract):
            if APPLICATION_PATTERNS.search(sentence):
                tokens = self._tokenize(sentence)
                excluded_ratio = len(tokens & set(self.excluded_minor_topics)) / max(len(tokens), 1)
                if excluded_ratio > 0.3:
                    continue
            abstract_without_app.append(sentence)
        self.clean_abstract = " ".join(abstract_without_app) if abstract_without_app else self.abstract

    def build_embedding_query(self) -> str:
        parts: list[str] = []
        if self.title:
            parts.append(self.title)
        if self.clean_abstract:
            parts.append(self.clean_abstract)
        if self.keywords:
            parts.append("Keywords: " + ", ".join(self.keywords[:8]))
        if self.subjects:
            parts.append("Subjects: " + ", ".join(self.subjects[:6]))
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "research_field": self.research_field,
            "main_topic_summary": self.title[:200] if self.title else (self.keywords[:3] if self.keywords else ""),
            "application_domain_summary": self.application_domain_text[:200] if self.application_domain_text else None,
            "excluded_minor_topics": self.excluded_minor_topics,
            "keyword_count": len(self.keywords),
            "subject_count": len(self.subjects),
        }

    @classmethod
    def from_doi_metadata(cls, metadata: dict[str, Any]) -> ManuscriptTopicProfile:
        return cls(
            title=metadata.get("title"),
            abstract=metadata.get("abstract"),
            keywords=metadata.get("keywords") or [],
            subjects=metadata.get("subjects") or [],
        )

    @classmethod
    def from_manuscript(cls, manuscript: Any) -> ManuscriptTopicProfile:
        keywords = []
        if hasattr(manuscript, "keywords_json") and manuscript.keywords_json:
            if isinstance(manuscript.keywords_json, list):
                keywords = manuscript.keywords_json
        return cls(
            title=getattr(manuscript, "title", None),
            abstract=getattr(manuscript, "abstract", None),
            keywords=keywords,
            body_text=getattr(manuscript, "body_text", None),
        )
