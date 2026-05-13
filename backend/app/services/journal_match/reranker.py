from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from app.models.match_request import MatchRequest


class MatchReranker:
    QUARTILE_SCORES = {"Q1": 1.0, "Q2": 0.8, "Q3": 0.6, "Q4": 0.4}
    DOMAIN_LEXICONS = {
        "network_security": {
            "triggers": {
                "attack",
                "attacks",
                "attack-surface",
                "firewall",
                "exposed",
                "exposure",
                "hardening",
                "network",
                "networks",
                "security",
                "cybersecurity",
                "intrusion",
                "misconfiguration",
                "packet",
                "packets",
                "tcp",
                "udp",
                "router",
                "routing",
                "vulnerability",
                "exploit",
                "malware",
                "threat",
                "zero-trust",
            },
            "required_groups": [
                {
                    "security",
                    "cybersecurity",
                    "cyber",
                    "network",
                    "networks",
                    "information",
                },
                {
                    "computer",
                    "computing",
                    "system",
                    "systems",
                    "software",
                    "data",
                    "model",
                    "detection",
                    "classification",
                    "prediction",
                    "analysis",
                    "attack",
                    "attacks",
                    "firewall",
                    "intrusion",
                    "malware",
                    "vulnerability",
                    "exploit",
                    "encryption",
                    "cryptography",
                    "internet",
                    "threat",
                    "privacy",
                    "authentication",
                    "authorization",
                    "packet",
                    "router",
                    "tcp",
                    "protocol",
                    "service",
                    "services",
                    "technology",
                    "engineering",
                    "digital",
                    "electronic",
                    "communication",
                    "communications",
                    "machine",
                    "learning",
                    "algorithm",
                    "artificial",
                    "intelligence",
                    "cipher",
                    "cryptanalysis",
                    "hacking",
                    "penetration",
                    "phishing",
                    "ransomware",
                    "virus",
                    "worm",
                    "botnet",
                    "ddos",
                    "forensic",
                    "forensics",
                    "risk",
                    "control",
                    "access",
                    "audit",
                    "identity",
                    "application",
                    "cloud",
                    "iot",
                },
            ],
            "candidate": {
                "firewall",
                "network",
                "networks",
                "security",
                "cybersecurity",
                "intrusion",
                "misconfiguration",
                "packet",
                "tcp",
                "udp",
                "routing",
                "systems",
                "distributed",
                "privacy",
                "cryptography",
                "vulnerability",
                "internet",
                "communications",
                "hardening",
                "service",
                "services",
                "attack",
                "exposure",
            },
        },
        "health_policy": {
            "triggers": {
                "medical",
                "medicine",
                "health",
                "healthcare",
                "clinical",
                "patient",
                "governance",
                "policy",
                "privacy",
                "compliance",
                "regulation",
            },
            "trigger_groups": [
                {"medical", "medicine", "health", "healthcare", "clinical", "patient"},
                {"data", "governance", "policy", "privacy", "compliance", "regulation"},
            ],
            "required_groups": [
                {"medical", "medicine", "health", "healthcare", "clinical", "patient"},
                {"data", "governance", "policy", "privacy", "compliance", "regulation"},
            ],
            "candidate": {
                "medical",
                "medicine",
                "health",
                "healthcare",
                "clinical",
                "patient",
                "data",
                "governance",
                "policy",
                "privacy",
                "compliance",
                "regulation",
            },
        },
        "publishing_ai": {
            "triggers": {
                "publishing",
                "publication",
                "scholarly",
                "journal",
                "analytics",
                "responsible",
                "artificial",
                "intelligence",
                "ai",
                "editorial",
            },
            "trigger_groups": [
                {"publishing", "publication", "scholarly", "journal", "editorial"},
                {"analytics", "responsible", "artificial", "intelligence", "ai"},
            ],
            "required_groups": [
                {"publishing", "publication", "scholarly", "journal", "editorial"},
                {"analytics", "responsible", "artificial", "intelligence", "ai"},
            ],
            "candidate": {
                "publishing",
                "publication",
                "scholarly",
                "journal",
                "editorial",
                "analytics",
                "responsible",
                "artificial",
                "intelligence",
                "ai",
                "ethics",
            },
        },
        "cs_crypto_algorithms": {
            "triggers": {
                "algorithm",
                "algorithms",
                "cryptanalytic",
                "cryptanalysis",
                "cryptography",
                "congruence",
                "congruences",
                "congruential",
                "polynomial",
                "truncated",
                "bits",
                "generator",
                "generators",
            },
            "trigger_groups": [
                {"cryptanalytic", "cryptanalysis", "cryptography", "congruence", "congruences", "congruential", "truncated"},
                {"algorithm", "algorithms", "polynomial", "time", "bits", "generator", "generators"},
            ],
            "required_groups": [
                {
                    "computer",
                    "computing",
                    "informatics",
                    "cryptography",
                    "cryptanalysis",
                    "cryptographic",
                    "algorithm",
                    "algorithms",
                    "computational",
                    "mathematics",
                    "number",
                    "theory",
                    "security",
                    "information",
                    "systems",
                    "software",
                    "engineering",
                    "communications",
                }
            ],
            "candidate": {
                "computer",
                "computing",
                "science",
                "informatics",
                "cryptography",
                "cryptanalysis",
                "cryptographic",
                "algorithm",
                "algorithms",
                "computational",
                "mathematics",
                "number",
                "theory",
                "security",
                "information",
                "systems",
                "software",
                "engineering",
                "communications",
                "discrete",
                "complexity",
            },
            "labels": ["computer science", "cryptography", "algorithms", "computational number theory"],
        },
        "scientific_computing": {
            "triggers": {
                "python",
                "numpy",
                "matlab",
                "julia",
                "r-project",
                "programming",
                "software",
                "library",
                "toolkit",
                "framework",
                "repository",
                "open-source",
                "open source",
                "computational",
                "numerical",
                "scientific",
                "computation",
                "computing",
                "simulation",
                "modelling",
                "modeling",
            },
            "trigger_groups": [
                {
                    "python",
                    "numpy",
                    "matlab",
                    "julia",
                    "r-project",
                    "programming",
                    "software",
                    "library",
                    "toolkit",
                    "framework",
                    "repository",
                    "open-source",
                    "open source",
                    "computational",
                    "computing",
                    "computation",
                    "numerical",
                    "simulation",
                    "modelling",
                    "modeling",
                },
                {
                    "scientific",
                    "science",
                    "data",
                    "analysis",
                    "method",
                    "methods",
                    "algorithm",
                    "algorithms",
                    "implementation",
                    "implementations",
                    "systems",
                },
            ],
            "required_groups": [
                {
                    "software",
                    "programming",
                    "library",
                    "toolkit",
                    "framework",
                    "computational",
                    "computing",
                    "computation",
                    "numerical",
                    "simulation",
                    "modelling",
                    "modeling",
                    "algorithm",
                    "algorithms",
                },
                {
                    "scientific",
                    "science",
                    "data",
                    "analysis",
                    "method",
                    "methods",
                    "implementation",
                    "implementations",
                    "systems",
                },
            ],
            "candidate": {
                "software",
                "computational",
                "scientific",
                "numerical",
                "programming",
                "python",
                "data",
                "computation",
                "computing",
                "simulation",
                "modelling",
                "library",
                "open-source",
                "algorithm",
                "implementation",
                "method",
                "analysis",
            },
            "labels": ["scientific computing", "computational science", "research software"],
        },
        "food_studies": {
            "triggers": {
                "food", "cuisine", "culinary", "gastronomy", "nutrition",
                "street-food", "street food", "cooking", "recipe", "diet",
                "beverage", "dining", "fermentation",
            },
            "trigger_groups": [
                {"food", "cuisine", "culinary", "gastronomy", "nutrition", "street-food", "street food", "cooking"},
                {"culture", "tradition", "urban", "street", "social", "market", "heritage", "identity"},
            ],
            "required_groups": [
                {"food", "cuisine", "culinary", "gastronomy", "nutrition", "street-food", "street food", "cooking", "diet"},
                {"culture", "tradition", "urban", "street", "social", "market", "heritage", "identity", "society"},
            ],
            "candidate": {
                "food", "cuisine", "culinary", "gastronomy", "nutrition",
                "street-food", "cooking", "recipe", "diet", "beverage",
                "dining", "gourmet", "culinary-arts",
            },
            "labels": ["food studies", "culinary studies", "gastronomy"],
        },
        "urban_studies": {
            "triggers": {
                "urban", "city", "cities", "sidewalk", "street", "downtown",
                "neighborhood", "public-space", "urbanization", "gentrification",
                "metropolitan", "civic", "municipal", "infrastructure",
                "town", "suburb", "urban-planning",
            },
            "trigger_groups": [
                {"urban", "city", "cities", "metropolitan", "municipal", "town", "suburb"},
                {"space", "street", "sidewalk", "neighborhood", "public", "planning", "infrastructure", "development"},
            ],
            "required_groups": [
                {"urban", "city", "cities", "metropolitan", "municipal", "town", "suburb", "public-space"},
                {"planning", "infrastructure", "development", "space", "street", "sidewalk", "neighborhood", "public", "culture", "society"},
            ],
            "candidate": {
                "urban", "city", "cities", "metropolitan", "municipal",
                "infrastructure", "planning", "neighborhood", "public-space",
                "civic", "urbanization", "gentrification", "housing",
                "transport", "zoning", "land-use",
            },
            "labels": ["urban studies", "urban planning", "urban geography"],
        },
        "cultural_studies": {
            "triggers": {
                "culture", "cultural", "heritage", "tradition", "folklore",
                "identity", "ethnographic", "intercultural", "multicultural",
                "subculture", "ethnicity", "custom", "ritual", "cultural-studies",
            },
            "trigger_groups": [
                {"culture", "cultural", "heritage", "tradition", "folklore", "identity", "custom", "ritual"},
                {"ethnographic", "intercultural", "society", "community", "ethnicity", "multicultural", "subculture"},
            ],
            "required_groups": [
                {"culture", "cultural", "heritage", "tradition", "folklore", "identity", "custom", "ritual"},
                {"ethnographic", "intercultural", "society", "community", "ethnicity", "multicultural", "subculture", "social"},
            ],
            "candidate": {
                "culture", "cultural", "heritage", "tradition", "folklore",
                "ethnographic", "identity", "ethnicity", "intercultural",
                "multicultural", "subculture", "custom", "ritual",
            },
            "labels": ["cultural studies", "cultural anthropology", "heritage studies"],
        },
        "asian_studies": {
            "triggers": {
                "asia", "asian", "southeast-asia", "east-asia", "south-asia",
                "vietnam", "vietnamese", "china", "japan", "korea", "india",
                "indonesia", "thailand", "cambodia", "laos", "myanmar",
                "philippines", "malaysia", "singapore", "taiwan",
            },
            "trigger_groups": [
                {"asia", "asian", "southeast-asia", "east-asia", "south-asia"},
                {"vietnam", "vietnamese", "china", "japan", "korea", "india", "indonesia", "thailand"},
            ],
            "required_groups": [
                {"asia", "asian", "southeast-asia", "east-asia", "south-asia"},
                {"vietnam", "vietnamese", "china", "japan", "korea", "india", "indonesia", "thailand", "cambodia", "laos"},
            ],
            "candidate": {
                "asia", "asian", "vietnam", "vietnamese", "china", "japan",
                "korea", "india", "southeast-asia", "east-asia", "south-asia",
                "indonesia", "thailand", "oriental", "pacific",
            },
            "labels": ["asian studies", "southeast asian studies", "east asian studies"],
        },
        "tourism_studies": {
            "triggers": {
                "tourism", "tourist", "hospitality", "travel", "destination",
                "visitor", "leisure", "hotel", "resort", "ecotourism",
                "backpacker", "sightseeing", "touring", "tour",
            },
            "trigger_groups": [
                {"tourism", "tourist", "hospitality", "travel", "destination", "tour"},
                {"leisure", "visitor", "hotel", "resort", "ecotourism", "backpacker"},
            ],
            "required_groups": [
                {"tourism", "tourist", "hospitality", "travel", "destination", "tour", "leisure"},
                {"visitor", "hotel", "resort", "ecotourism", "backpacker", "industry", "management", "development"},
            ],
            "candidate": {
                "tourism", "tourist", "hospitality", "travel", "destination",
                "leisure", "hotel", "resort", "ecotourism", "visitor",
            },
            "labels": ["tourism studies", "hospitality management", "travel research"],
        },
        "sociology_anthropology": {
            "triggers": {
                "sociology", "anthropology", "ethnographic", "ethnography",
                "qualitative", "community", "migration", "diaspora",
                "inequality", "class", "gender", "race", "ethnicity",
                "social-structure", "social-movement", "social-theory",
            },
            "trigger_groups": [
                {"sociology", "anthropology", "ethnographic", "ethnography", "qualitative"},
                {"community", "migration", "diaspora", "inequality", "social", "class", "gender", "race"},
            ],
            "required_groups": [
                {"sociology", "anthropology", "ethnographic", "ethnography", "qualitative", "social-theory"},
                {"community", "migration", "diaspora", "inequality", "social", "class", "gender", "race", "ethnicity"},
            ],
            "candidate": {
                "sociology", "anthropology", "ethnographic", "qualitative",
                "community", "migration", "diaspora", "inequality", "social",
                "class", "gender", "race", "ethnicity",
            },
            "labels": ["sociology", "anthropology", "social science"],
        },
        "environmental_studies": {
            "triggers": {
                "environment", "environmental", "climate", "ecological",
                "ecology", "sustainability", "conservation", "biodiversity",
                "ecosystem", "pollution", "renewable", "green", "carbon",
                "emission", "climate-change", "global-warming",
            },
            "trigger_groups": [
                {"environment", "environmental", "climate", "ecological", "ecology", "climate-change"},
                {"sustainability", "conservation", "biodiversity", "ecosystem", "renewable", "green", "carbon"},
            ],
            "required_groups": [
                {"environment", "environmental", "climate", "ecological", "ecology", "climate-change", "global-warming"},
                {"sustainability", "conservation", "biodiversity", "ecosystem", "renewable", "green", "carbon", "pollution"},
            ],
            "candidate": {
                "environment", "environmental", "climate", "ecological",
                "sustainability", "conservation", "biodiversity", "renewable",
                "green", "carbon", "emission", "ecosystem", "pollution",
            },
            "labels": ["environmental studies", "environmental science", "sustainability research"],
        },
    }
    HARD_INCOMPATIBLE_TERMS = {
        "cs_crypto_algorithms": {
            "medicine",
            "medical",
            "surgery",
            "surgical",
            "hematology",
            "haematology",
            "clinical",
            "clinic",
            "biology",
            "biological",
            "biomedical",
            "health",
            "healthcare",
            "patient",
            "patients",
            "oncology",
            "cardiology",
            "pharmacology",
        },
        "network_security": {
            "anthropology",
            "archaeology",
            "criminology",
            "demography",
            "diplomacy",
            "geography",
            "humanities",
            "peace",
            "sociology",
            "theology",
        },
        "scientific_computing": {
            "anthropology", "archaeology", "sociology", "folklor", "culinary",
            "cuisine", "gastronomy", "urban", "sidewalk", "tourism",
            "hospitality", "biography", "archives", "manuscripts",
        },
        "food_studies": {
            "medicine", "clinical", "surgery", "cardiology", "oncology",
            "astronomy", "astrophysics", "nuclear", "particle", "quantum",
            "cryptography", "algorithm", "engineering",
        },
        "urban_studies": {
            "medicine", "clinical", "astronomy", "astrophysics", "nuclear",
            "cryptography", "algorithm", "software", "programming",
        },
        "cultural_studies": {
            "medicine", "clinical", "astronomy", "astrophysics", "nuclear",
            "engineering", "programming", "cryptography",
        },
        "asian_studies": {
            "astronomy", "astrophysics", "nuclear", "particle", "quantum",
            "cardiology", "oncology", "surgery",
        },
        "tourism_studies": {
            "medicine", "clinical", "astronomy", "astrophysics", "nuclear",
            "cryptography", "software", "programming",
        },
        "sociology_anthropology": {
            "astronomy", "astrophysics", "nuclear", "particle", "quantum",
            "cryptography", "algorithm", "software", "programming",
        },
        "environmental_studies": {
            "astronomy", "astrophysics", "nuclear", "particle", "quantum",
            "cryptography", "algorithm", "programming",
        },
    }

    def _tokenize(self, text: str) -> set[str]:
        return {token for token in re.findall(r"[a-z][a-z0-9\-]{2,}", text.lower())}

    def _scope_overlap(self, manuscript_text: str, candidate: dict[str, Any]) -> float:
        document_tokens = self._tokenize(candidate.get("document", ""))
        manuscript_tokens = self._tokenize(manuscript_text)
        if not manuscript_tokens or not document_tokens:
            return 0.0
        overlap = manuscript_tokens & document_tokens
        return round(len(overlap) / max(len(manuscript_tokens), 1), 4)

    def active_domains(self, manuscript_text: str) -> list[str]:
        manuscript_tokens = self._tokenize(manuscript_text)
        active: list[str] = []
        for name, lexicon in self.DOMAIN_LEXICONS.items():
            trigger_groups = lexicon.get("trigger_groups") or []
            if trigger_groups:
                if all(manuscript_tokens & set(group) for group in trigger_groups):
                    active.append(name)
                continue
            if manuscript_tokens & lexicon["triggers"]:
                active.append(name)
        return active

    def inferred_domain_labels(self, manuscript_text: str) -> list[str]:
        labels: list[str] = []
        for domain_name in self.active_domains(manuscript_text):
            domain_labels = self.DOMAIN_LEXICONS.get(domain_name, {}).get("labels") or [domain_name.replace("_", " ")]
            for label in domain_labels:
                if label not in labels:
                    labels.append(label)
        return labels

    def hard_domain_mismatch(self, manuscript_text: str, candidate: dict[str, Any]) -> list[str]:
        metadata = candidate.get("metadata", {})
        subject_text = metadata.get("subject_labels") or metadata.get("topic_tags") or ""
        if isinstance(subject_text, (list, tuple, set)):
            subject_blob = " ".join(str(item) for item in subject_text)
        else:
            subject_blob = str(subject_text)
        subject_tokens = self._tokenize(subject_blob)
        reasons: list[str] = []
        for domain_name in self.active_domains(manuscript_text):
            incompatible = self.HARD_INCOMPATIBLE_TERMS.get(domain_name, set())
            if subject_tokens & incompatible:
                reasons.append(f"{domain_name}_hard_subject_mismatch")
        return reasons

    def _domain_fit(self, manuscript_text: str, candidate: dict[str, Any]) -> tuple[float, list[str]]:
        manuscript_tokens = self._tokenize(manuscript_text)
        document_tokens = self._tokenize(candidate.get("document", ""))
        metadata = candidate.get("metadata", {})
        metadata_tokens = self._tokenize(
            " ".join(
                str(metadata.get(key) or "")
                for key in ("title", "subject_labels", "publisher")
            )
        )
        candidate_tokens = document_tokens | metadata_tokens
        reasons: list[str] = []
        active_domains = self.active_domains(manuscript_text)
        if not active_domains:
            return 0.5, reasons
        hard_mismatch = self.hard_domain_mismatch(manuscript_text, candidate)
        if hard_mismatch:
            return 0.0, hard_mismatch
        scores: list[float] = []
        for domain_name in active_domains:
            lexicon = self.DOMAIN_LEXICONS[domain_name]
            required_groups = lexicon.get("required_groups") or []
            missing_required = [
                group
                for group in required_groups
                if not candidate_tokens & set(group)
            ]
            if missing_required:
                scores.append(0.0)
                reasons.append(f"{domain_name}_mismatch")
                continue
            matched = candidate_tokens & lexicon["candidate"]
            if matched:
                scores.append(min(1.0, 0.35 + 0.15 * len(matched)))
            else:
                scores.append(0.0)
                reasons.append(f"{domain_name}_mismatch")
        return round(max(scores) if scores else 0.0, 4), reasons

    @staticmethod
    def _metrics_for_scoring(metadata: dict[str, Any]) -> dict[str, Any]:
        verified = metadata.get("verified_metrics")
        if isinstance(verified, dict):
            return verified
        return metadata

    def _quality_fit(self, metadata: dict[str, Any]) -> float:
        scoring_metadata = self._metrics_for_scoring(metadata)
        quartile = str(scoring_metadata.get("sjr_quartile") or scoring_metadata.get("jcr_quartile") or "").upper()
        quartile_score = self.QUARTILE_SCORES.get(quartile, 0.5)
        citescore = float(scoring_metadata.get("citescore") or 0.0)
        citescore_score = min(citescore / 20.0, 1.0)
        indexed_bonus = 0.1 if scoring_metadata.get("indexed_scopus") else 0.0
        indexed_bonus += 0.1 if scoring_metadata.get("indexed_wos") else 0.0
        return round(min(1.0, quartile_score * 0.7 + citescore_score * 0.2 + indexed_bonus), 4)

    def _policy_fit(self, request: MatchRequest, metadata: dict[str, Any]) -> float:
        scoring_metadata = self._metrics_for_scoring(metadata)
        score = 0.4
        if scoring_metadata.get("is_open_access"):
            score += 0.2
        if request.apc_budget_usd is not None and scoring_metadata.get("apc_usd") is not None:
            try:
                if float(scoring_metadata["apc_usd"]) <= float(request.apc_budget_usd):
                    score += 0.2
            except (TypeError, ValueError):
                pass
        if request.max_review_weeks is not None and scoring_metadata.get("avg_review_weeks") is not None:
            try:
                if float(scoring_metadata["avg_review_weeks"]) <= float(request.max_review_weeks):
                    score += 0.2
            except (TypeError, ValueError):
                pass
        return round(min(score, 1.0), 4)

    def _freshness(self, metadata: dict[str, Any]) -> float:
        if metadata.get("entity_type") == "cfp":
            deadline_raw = metadata.get("full_paper_deadline") or metadata.get("abstract_deadline")
            if deadline_raw:
                try:
                    deadline = datetime.fromisoformat(str(deadline_raw).replace("Z", "+00:00"))
                    if deadline.tzinfo is None:
                        deadline = deadline.replace(tzinfo=timezone.utc)
                    days = (deadline - datetime.now(timezone.utc)).days
                    if days < 0:
                        return 0.0
                    if days <= 30:
                        return 1.0
                    if days <= 90:
                        return 0.8
                except ValueError:
                    pass
            return 0.5
        publication_year = metadata.get("publication_year")
        if publication_year is None:
            return 0.5
        age = max(0, datetime.now(timezone.utc).year - int(publication_year))
        return round(max(0.1, 1.0 - age / 10.0), 4)

    def _penalty(self, request: MatchRequest, metadata: dict[str, Any], scope_overlap_score: float, domain_fit_score: float) -> float:
        scoring_metadata = self._metrics_for_scoring(metadata)
        penalty = 0.0
        if request.apc_budget_usd is not None and scoring_metadata.get("apc_usd") is not None:
            try:
                if float(scoring_metadata["apc_usd"]) > float(request.apc_budget_usd):
                    penalty += 0.2
            except (TypeError, ValueError):
                pass
        if request.max_review_weeks is not None and scoring_metadata.get("avg_review_weeks") is not None:
            try:
                if float(scoring_metadata["avg_review_weeks"]) > float(request.max_review_weeks):
                    penalty += 0.15
            except (TypeError, ValueError):
                pass
        if scope_overlap_score < 0.02:
            penalty += 0.2
        if domain_fit_score == 0.0:
            penalty += 0.45
        elif domain_fit_score < 0.35:
            penalty += 0.25
        if metadata.get("entity_type") == "article" and metadata.get("is_retracted"):
            penalty += 0.5
        warning_flags = metadata.get("warning_flags")
        if isinstance(warning_flags, list) and "suspected_book_series" in warning_flags:
            penalty += 0.3
        return round(min(penalty, 1.0), 4)

    def rerank(
        self,
        *,
        request: MatchRequest,
        manuscript_text: str,
        readiness_score: float,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        for candidate in candidates:
            metadata = candidate.get("metadata", {})
            retrieval_score = float(candidate.get("retrieval_score", 0.0))
            scope_overlap_score = self._scope_overlap(manuscript_text, candidate)
            domain_fit_score, domain_mismatch_reasons = self._domain_fit(manuscript_text, candidate)
            quality_fit_score = self._quality_fit(metadata)
            policy_fit_score = self._policy_fit(request, metadata)
            freshness_score = self._freshness(metadata)
            manuscript_readiness_score = readiness_score
            penalty_score = self._penalty(request, metadata, scope_overlap_score, domain_fit_score)
            final_score = (
                0.35 * retrieval_score
                + 0.15 * scope_overlap_score
                + 0.20 * domain_fit_score
                + 0.10 * quality_fit_score
                + 0.05 * policy_fit_score
                + 0.05 * freshness_score
                + 0.10 * manuscript_readiness_score
                - penalty_score
            )
            candidate["score_breakdown"] = {
                "retrieval_score": round(retrieval_score, 4),
                "scope_overlap_score": round(scope_overlap_score, 4),
                "domain_fit_score": round(domain_fit_score, 4),
                "domain_mismatch_reasons": domain_mismatch_reasons,
                "quality_fit_score": round(quality_fit_score, 4),
                "policy_fit_score": round(policy_fit_score, 4),
                "freshness_score": round(freshness_score, 4),
                "manuscript_readiness_score": round(manuscript_readiness_score, 4),
                "penalty_score": round(penalty_score, 4),
                "final_score": round(final_score, 4),
            }
            candidate["final_score"] = round(final_score, 4)
            scored.append(candidate)
        scored.sort(
            key=lambda item: (
                item["final_score"],
                item["score_breakdown"]["domain_fit_score"],
                item["score_breakdown"]["retrieval_score"],
                str(item.get("metadata", {}).get("primary_label") or item.get("metadata", {}).get("title") or item.get("record_id") or ""),
            ),
            reverse=True,
        )
        for rank, candidate in enumerate(scored, start=1):
            candidate["rank"] = rank
        return scored


match_reranker = MatchReranker()
