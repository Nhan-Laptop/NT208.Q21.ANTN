"""
Journal Finder — intelligent journal recommendation.

Approaches (auto-selected):
1. SPECTER2 / SciBERT embeddings  (when ``sentence-transformers`` is installed)
2. TF-IDF cosine similarity       (built-in fallback, zero extra deps)

Both paths share a single expanded JOURNAL_DB and domain-detection logic.
"""

import math
import re
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy deps – all guarded with try/except
# ---------------------------------------------------------------------------
_NP_AVAILABLE = False
try:
    import numpy as np
    _NP_AVAILABLE = True
except ImportError:
    np = None  # type: ignore[assignment]

_ST_AVAILABLE = False
_model_cache = None
try:
    from sentence_transformers import SentenceTransformer
    _ST_AVAILABLE = True
except ImportError:
    SentenceTransformer = None  # type: ignore[assignment,misc]

TOKEN_RE = re.compile(r"[a-zA-Z]{3,}")

# ---------------------------------------------------------------------------
# Domain keywords
# ---------------------------------------------------------------------------
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "computer_science": ["algorithm", "software", "programming", "computing", "database", "network", "system"],
    "machine_learning": ["neural", "deep", "learning", "model", "training", "classification", "prediction"],
    "nlp": ["language", "text", "semantic", "parsing", "translation", "sentiment", "nlp", "linguistic"],
    "medicine": ["clinical", "patient", "disease", "treatment", "diagnosis", "therapy", "medical", "health"],
    "biology": ["gene", "protein", "cell", "molecular", "biological", "genome", "organism"],
    "physics": ["quantum", "particle", "energy", "field", "wave", "matter", "physics"],
    "chemistry": ["chemical", "reaction", "compound", "molecular", "synthesis", "catalyst"],
    "engineering": ["design", "system", "optimization", "control", "manufacturing", "process"],
    "social_science": ["social", "behavior", "society", "culture", "economic", "policy", "survey"],
    "education": ["learning", "teaching", "student", "education", "curriculum", "assessment"],
}

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class JournalCandidate:
    name: str
    scope: str
    url: str
    issn: str | None = None
    impact_factor: float | None = None
    publisher: str | None = None
    open_access: bool = False
    domains: list[str] = field(default_factory=list)
    h_index: int | None = None
    review_time_weeks: int | None = None
    acceptance_rate: float | None = None


# ---------------------------------------------------------------------------
# Expanded Journal Database (merged V1+V2)
# ---------------------------------------------------------------------------
JOURNAL_DB: list[JournalCandidate] = [
    # === Computer Science & AI ===
    JournalCandidate(
        name="IEEE Access",
        scope="computer science, artificial intelligence, data science, engineering applications, electronics, IoT, cloud computing, big data",
        url="https://ieeeaccess.ieee.org/",
        issn="2169-3536", impact_factor=3.9, publisher="IEEE", open_access=True,
        domains=["computer_science", "engineering"], h_index=204, review_time_weeks=8, acceptance_rate=0.35,
    ),
    JournalCandidate(
        name="ACM Transactions on Information Systems",
        scope="information retrieval, digital libraries, search engines, NLP, text mining, recommendation systems, knowledge graphs",
        url="https://dl.acm.org/journal/tois",
        issn="1046-8188", impact_factor=5.4, publisher="ACM",
        domains=["computer_science", "nlp"], h_index=112, review_time_weeks=16, acceptance_rate=0.15,
    ),
    JournalCandidate(
        name="Expert Systems with Applications",
        scope="AI applications, decision systems, machine learning, expert systems, neural networks, fuzzy systems, knowledge-based systems",
        url="https://www.sciencedirect.com/journal/expert-systems-with-applications",
        issn="0957-4174", impact_factor=8.5, publisher="Elsevier",
        domains=["computer_science", "machine_learning"], h_index=198, review_time_weeks=12, acceptance_rate=0.20,
    ),
    JournalCandidate(
        name="Artificial Intelligence",
        scope="artificial intelligence, reasoning, planning, knowledge representation, robotics, multi-agent systems, logic programming",
        url="https://www.sciencedirect.com/journal/artificial-intelligence",
        issn="0004-3702", impact_factor=14.4, publisher="Elsevier",
        domains=["computer_science", "machine_learning"], h_index=178, review_time_weeks=20, acceptance_rate=0.10,
    ),
    JournalCandidate(
        name="IEEE Transactions on Neural Networks and Learning Systems",
        scope="neural networks, deep learning, machine learning, pattern recognition, reinforcement learning, computational intelligence",
        url="https://ieeexplore.ieee.org/xpl/RecentIssue.jsp?punumber=5962385",
        issn="2162-237X", impact_factor=10.4, publisher="IEEE",
        domains=["machine_learning", "computer_science"], h_index=245, review_time_weeks=16, acceptance_rate=0.12,
    ),
    JournalCandidate(
        name="Nature Machine Intelligence",
        scope="machine learning, artificial intelligence, robotics, computer vision, NLP, AI ethics, autonomous systems",
        url="https://www.nature.com/natmachintell/",
        issn="2522-5839", impact_factor=18.8, publisher="Nature",
        domains=["machine_learning", "computer_science"], h_index=85, review_time_weeks=12, acceptance_rate=0.08,
    ),
    JournalCandidate(
        name="Journal of Machine Learning Research",
        scope="machine learning, statistical learning, deep learning, optimization, theoretical foundations",
        url="https://jmlr.org/",
        issn="1532-4435", impact_factor=6.0, publisher="JMLR", open_access=True,
        domains=["machine_learning"], h_index=234, review_time_weeks=24, acceptance_rate=0.15,
    ),
    JournalCandidate(
        name="ACM Computing Surveys",
        scope="computer science surveys, literature reviews, systematic reviews, state-of-the-art analysis",
        url="https://dl.acm.org/journal/csur",
        issn="0360-0300", impact_factor=16.6, publisher="ACM",
        domains=["computer_science"], h_index=198, review_time_weeks=20, acceptance_rate=0.12,
    ),
    # === NLP & Text Mining ===
    JournalCandidate(
        name="Computational Linguistics",
        scope="computational linguistics, NLP, natural language processing, parsing, semantics, machine translation",
        url="https://direct.mit.edu/coli",
        issn="0891-2017", impact_factor=3.7, publisher="MIT Press",
        domains=["nlp", "computer_science"], h_index=112, review_time_weeks=16, acceptance_rate=0.18,
    ),
    JournalCandidate(
        name="Transactions of the ACL",
        scope="computational linguistics, NLP, language models, text generation, question answering, dialogue systems",
        url="https://transacl.org/",
        issn="2307-387X", impact_factor=4.2, publisher="ACL", open_access=True,
        domains=["nlp"], h_index=89, review_time_weeks=12, acceptance_rate=0.20,
    ),
    # === Scientometrics & Bibliometrics ===
    JournalCandidate(
        name="Journal of Informetrics",
        scope="bibliometrics, scientometrics, citation analysis, research evaluation, altmetrics, h-index, impact metrics",
        url="https://www.sciencedirect.com/journal/journal-of-informetrics",
        issn="1751-1577", impact_factor=3.7, publisher="Elsevier",
        domains=["social_science"], h_index=89, review_time_weeks=14, acceptance_rate=0.22,
    ),
    JournalCandidate(
        name="Scientometrics",
        scope="science of science, research metrics, publication analysis, h-index, impact factor, citation networks",
        url="https://www.springer.com/journal/11192",
        issn="0138-9130", impact_factor=3.5, publisher="Springer",
        domains=["social_science"], h_index=134, review_time_weeks=12, acceptance_rate=0.25,
    ),
    JournalCandidate(
        name="Quantitative Science Studies",
        scope="quantitative studies, bibliometrics, science policy, research assessment, open science",
        url="https://direct.mit.edu/qss",
        issn="2641-3337", impact_factor=6.4, publisher="MIT Press", open_access=True,
        domains=["social_science"], h_index=34, review_time_weeks=10, acceptance_rate=0.28,
    ),
    # === Medical & Health Sciences ===
    JournalCandidate(
        name="The Lancet",
        scope="medicine, clinical research, public health, epidemiology, healthcare, medical policy",
        url="https://www.thelancet.com/",
        issn="0140-6736", impact_factor=168.9, publisher="Elsevier",
        domains=["medicine"], h_index=745, review_time_weeks=4, acceptance_rate=0.05,
    ),
    JournalCandidate(
        name="PLOS ONE",
        scope="multidisciplinary, biology, medicine, science, research methodology, data science",
        url="https://journals.plos.org/plosone/",
        issn="1932-6203", impact_factor=3.7, publisher="PLOS", open_access=True,
        domains=["biology", "medicine"], h_index=378, review_time_weeks=12, acceptance_rate=0.55,
    ),
    JournalCandidate(
        name="BMC Medical Informatics and Decision Making",
        scope="medical informatics, health IT, clinical decision support, electronic health records, telemedicine",
        url="https://bmcmedinformdecismak.biomedcentral.com/",
        issn="1472-6947", impact_factor=3.3, publisher="BMC", open_access=True,
        domains=["medicine", "computer_science"], h_index=89, review_time_weeks=10, acceptance_rate=0.40,
    ),
    JournalCandidate(
        name="Journal of Medical Internet Research",
        scope="digital health, eHealth, mHealth, telemedicine, health informatics, wearables",
        url="https://www.jmir.org/",
        issn="1438-8871", impact_factor=7.4, publisher="JMIR", open_access=True,
        domains=["medicine", "computer_science"], h_index=156, review_time_weeks=8, acceptance_rate=0.25,
    ),
    # === Engineering ===
    JournalCandidate(
        name="Engineering Applications of Artificial Intelligence",
        scope="AI in engineering, control systems, robotics, manufacturing, optimization, automation",
        url="https://www.sciencedirect.com/journal/engineering-applications-of-artificial-intelligence",
        issn="0952-1976", impact_factor=8.0, publisher="Elsevier",
        domains=["engineering", "machine_learning"], h_index=145, review_time_weeks=14, acceptance_rate=0.18,
    ),
    JournalCandidate(
        name="IEEE Transactions on Industrial Informatics",
        scope="industrial informatics, IoT, Industry 4.0, smart manufacturing, cyber-physical systems",
        url="https://ieeexplore.ieee.org/xpl/RecentIssue.jsp?punumber=9424",
        issn="1551-3203", impact_factor=12.3, publisher="IEEE",
        domains=["engineering", "computer_science"], h_index=178, review_time_weeks=12, acceptance_rate=0.15,
    ),
    # === Information Systems ===
    JournalCandidate(
        name="Information Systems Research",
        scope="information systems, IT strategy, digital transformation, business analytics, e-commerce",
        url="https://pubsonline.informs.org/journal/isre",
        issn="1047-7047", impact_factor=5.0, publisher="INFORMS",
        domains=["computer_science", "social_science"], h_index=156, review_time_weeks=20, acceptance_rate=0.10,
    ),
    JournalCandidate(
        name="MIS Quarterly",
        scope="management information systems, IT governance, digital business, enterprise systems, IS research",
        url="https://www.misq.org/",
        issn="0276-7783", impact_factor=7.0, publisher="MIS Quarterly",
        domains=["computer_science", "social_science"], h_index=234, review_time_weeks=24, acceptance_rate=0.08,
    ),
    JournalCandidate(
        name="Journal of the Association for Information Systems",
        scope="information systems research, IS theory, IS methodology, enterprise systems",
        url="https://aisel.aisnet.org/jais/",
        issn="1536-9323", impact_factor=4.5, publisher="AIS", open_access=True,
        domains=["computer_science", "social_science"], h_index=89, review_time_weeks=18, acceptance_rate=0.15,
    ),
    # === Security & Privacy ===
    JournalCandidate(
        name="Computers & Security",
        scope="cybersecurity, network security, cryptography, privacy, malware, intrusion detection, blockchain",
        url="https://www.sciencedirect.com/journal/computers-and-security",
        issn="0167-4048", impact_factor=5.6, publisher="Elsevier",
        domains=["computer_science"], h_index=123, review_time_weeks=12, acceptance_rate=0.20,
    ),
    JournalCandidate(
        name="IEEE Transactions on Information Forensics and Security",
        scope="digital forensics, biometrics, security protocols, surveillance, watermarking, privacy",
        url="https://ieeexplore.ieee.org/xpl/RecentIssue.jsp?punumber=10206",
        issn="1556-6013", impact_factor=6.8, publisher="IEEE",
        domains=["computer_science"], h_index=167, review_time_weeks=14, acceptance_rate=0.12,
    ),
    JournalCandidate(
        name="ACM Transactions on Privacy and Security",
        scope="privacy, security, access control, authentication, cryptographic protocols",
        url="https://dl.acm.org/journal/tops",
        issn="2471-2566", impact_factor=3.9, publisher="ACM",
        domains=["computer_science"], h_index=78, review_time_weeks=16, acceptance_rate=0.18,
    ),
    # === Education & E-Learning ===
    JournalCandidate(
        name="Computers & Education",
        scope="educational technology, e-learning, online education, learning analytics, MOOC, adaptive learning",
        url="https://www.sciencedirect.com/journal/computers-and-education",
        issn="0360-1315", impact_factor=12.0, publisher="Elsevier",
        domains=["education", "computer_science"], h_index=234, review_time_weeks=14, acceptance_rate=0.15,
    ),
    JournalCandidate(
        name="The Internet and Higher Education",
        scope="online learning, distance education, MOOCs, higher education technology, blended learning",
        url="https://www.sciencedirect.com/journal/the-internet-and-higher-education",
        issn="1096-7516", impact_factor=8.6, publisher="Elsevier",
        domains=["education"], h_index=123, review_time_weeks=12, acceptance_rate=0.18,
    ),
    JournalCandidate(
        name="British Journal of Educational Technology",
        scope="educational technology, digital learning, technology-enhanced learning, pedagogy",
        url="https://bera-journals.onlinelibrary.wiley.com/journal/14678535",
        issn="0007-1013", impact_factor=6.7, publisher="Wiley",
        domains=["education"], h_index=145, review_time_weeks=10, acceptance_rate=0.20,
    ),
    # === Natural Sciences ===
    JournalCandidate(
        name="Nature Communications",
        scope="multidisciplinary, physics, chemistry, biology, materials science, earth science",
        url="https://www.nature.com/ncomms/",
        issn="2041-1723", impact_factor=16.6, publisher="Nature", open_access=True,
        domains=["biology", "physics", "chemistry"], h_index=456, review_time_weeks=8, acceptance_rate=0.12,
    ),
    JournalCandidate(
        name="Scientific Reports",
        scope="multidisciplinary, natural sciences, engineering, clinical research, methodology",
        url="https://www.nature.com/srep/",
        issn="2045-2322", impact_factor=4.6, publisher="Nature", open_access=True,
        domains=["biology", "physics", "chemistry", "engineering"], h_index=312, review_time_weeks=10, acceptance_rate=0.45,
    ),
    # === Social Sciences ===
    JournalCandidate(
        name="Social Science Computer Review",
        scope="computational social science, social media analysis, digital humanities, network analysis",
        url="https://journals.sagepub.com/home/ssc",
        issn="0894-4393", impact_factor=4.1, publisher="SAGE",
        domains=["social_science", "computer_science"], h_index=89, review_time_weeks=14, acceptance_rate=0.22,
    ),
    JournalCandidate(
        name="Big Data & Society",
        scope="big data, data science, digital society, data ethics, algorithmic governance",
        url="https://journals.sagepub.com/home/bds",
        issn="2053-9517", impact_factor=6.5, publisher="SAGE", open_access=True,
        domains=["social_science", "computer_science"], h_index=67, review_time_weeks=12, acceptance_rate=0.25,
    ),
    # === Data Science & Analytics ===
    JournalCandidate(
        name="Data Mining and Knowledge Discovery",
        scope="data mining, knowledge discovery, machine learning, pattern recognition, big data analytics",
        url="https://www.springer.com/journal/10618",
        issn="1384-5810", impact_factor=4.8, publisher="Springer",
        domains=["computer_science", "machine_learning"], h_index=112, review_time_weeks=14, acceptance_rate=0.18,
    ),
    JournalCandidate(
        name="IEEE Transactions on Knowledge and Data Engineering",
        scope="knowledge engineering, data engineering, databases, data mining, semantic web",
        url="https://ieeexplore.ieee.org/xpl/RecentIssue.jsp?punumber=69",
        issn="1041-4347", impact_factor=8.9, publisher="IEEE",
        domains=["computer_science"], h_index=234, review_time_weeks=16, acceptance_rate=0.12,
    ),
]


# ---------------------------------------------------------------------------
# JournalFinder
# ---------------------------------------------------------------------------

class JournalFinder:
    """
    Intelligent Journal Recommender.

    * If ``sentence-transformers`` + ``numpy`` are installed -> uses SPECTER2 /
      SciBERT embeddings for semantic matching.
    * Otherwise -> falls back to TF-IDF cosine similarity (zero extra deps).
    """

    def __init__(self, use_ml: bool = True) -> None:
        self._model = None
        self._journal_embeddings = None
        self._use_ml = use_ml and _ST_AVAILABLE and _NP_AVAILABLE
        if self._use_ml:
            self._load_model()

    def _load_model(self) -> None:
        global _model_cache
        if _model_cache is not None:
            self._model = _model_cache
            self._precompute_journal_embeddings()
            return
        for name in ("allenai/specter2", "allenai/scibert_scivocab_uncased"):
            try:
                logger.info("Loading model %s ...", name)
                self._model = SentenceTransformer(name)
                _model_cache = self._model
                logger.info("Model %s loaded", name)
                self._precompute_journal_embeddings()
                return
            except Exception as exc:
                logger.warning("Failed to load %s: %s", name, exc)
        logger.warning("No ML model available - falling back to TF-IDF.")
        self._use_ml = False

    def _precompute_journal_embeddings(self) -> None:
        if self._model is None:
            return
        texts = [f"{j.name}. {j.scope}" for j in JOURNAL_DB]
        self._journal_embeddings = self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        logger.info("Pre-computed embeddings for %d journals", len(JOURNAL_DB))

    @staticmethod
    def _vectorize(text: str) -> Counter[str]:
        return Counter(t.lower() for t in TOKEN_RE.findall(text))

    @staticmethod
    def _cosine(v1: Counter[str], v2: Counter[str]) -> float:
        dot = sum(v1[k] * v2.get(k, 0) for k in v1)
        if dot == 0:
            return 0.0
        n1 = math.sqrt(sum(x * x for x in v1.values()))
        n2 = math.sqrt(sum(x * x for x in v2.values()))
        return dot / (n1 * n2) if n1 and n2 else 0.0

    @staticmethod
    def _detect_domains(text: str) -> list[str]:
        low = text.lower()
        return [d for d, kws in DOMAIN_KEYWORDS.items() if sum(1 for k in kws if k in low) >= 2]

    @staticmethod
    def _domain_bonus(journal: JournalCandidate, detected: list[str]) -> float:
        if not detected or not journal.domains:
            return 0.0
        return len(set(journal.domains) & set(detected)) * 0.05

    def recommend(
        self,
        abstract: str,
        title: str | None = None,
        top_k: int = 5,
        prefer_open_access: bool = False,
        min_impact_factor: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return ranked journal recommendations.

        Output dict always contains keys used by ``JournalItem`` schema:
        ``journal``, ``score``, ``reason``, ``url``, ``impact_factor``,
        ``publisher``, ``open_access``.
        """
        query_text = f"{title}. {abstract}" if title else abstract
        detected = self._detect_domains(query_text)

        journals = JOURNAL_DB
        if min_impact_factor is not None:
            journals = [j for j in journals if j.impact_factor is None or j.impact_factor >= min_impact_factor]

        if self._use_ml and self._model is not None and self._journal_embeddings is not None:
            raw = self._score_embeddings(query_text, journals)
        else:
            raw = self._score_tfidf(query_text, journals)

        final: list[tuple[float, JournalCandidate]] = []
        for sc, j in raw:
            sc += self._domain_bonus(j, detected)
            if prefer_open_access and j.open_access:
                sc *= 1.1
            final.append((sc, j))

        ranked = sorted(final, key=lambda x: x[0], reverse=True)[:top_k]
        method = "SPECTER2 embedding" if self._use_ml else "TF-IDF keyword"

        out: list[dict[str, Any]] = []
        for score, j in ranked:
            out.append({
                "journal": j.name,
                "score": round(min(score, 1.0), 4),
                "reason": f"Matched via {method} similarity. Scope: {j.scope[:100]}...",
                "url": j.url,
                "impact_factor": j.impact_factor,
                "publisher": j.publisher,
                "open_access": j.open_access,
                # extra metadata
                "issn": j.issn,
                "h_index": j.h_index,
                "review_time_weeks": j.review_time_weeks,
                "acceptance_rate": j.acceptance_rate,
                "domains": j.domains,
                "detected_domains": detected,
            })
        return out

    def _score_embeddings(self, query_text: str, journals: list[JournalCandidate]) -> list[tuple[float, JournalCandidate]]:
        qe = self._model.encode([query_text], convert_to_numpy=True, show_progress_bar=False)[0]
        idx_map = {id(j): i for i, j in enumerate(JOURNAL_DB)}
        scores: list[tuple[float, JournalCandidate]] = []
        for j in journals:
            je = self._journal_embeddings[idx_map[id(j)]]
            sim = float(np.dot(qe, je) / (np.linalg.norm(qe) * np.linalg.norm(je) + 1e-8))
            scores.append(((sim + 1) / 2, j))
        return scores

    def _score_tfidf(self, query_text: str, journals: list[JournalCandidate]) -> list[tuple[float, JournalCandidate]]:
        qv = self._vectorize(query_text)
        return [(self._cosine(qv, self._vectorize(f"{j.name} {j.scope}")), j) for j in journals]

    @property
    def is_ml_enabled(self) -> bool:
        return self._use_ml and self._model is not None

    @property
    def model_name(self) -> str:
        if self._model is not None:
            return getattr(self._model, "_model_card_text", "SPECTER2/SciBERT")
        return "TF-IDF (no ML model)"


# Singleton
journal_finder = JournalFinder(use_ml=True)
