"""
Journal Finder — intelligent journal recommendation backed by ChromaDB.

Queries a persistent ChromaDB vector store (seeded by ``backend/crawler/``)
using SentenceTransformer embeddings.  Falls back to an empty list if the
DB is missing or empty — never crashes the chat.
"""

import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy deps – all guarded
# ---------------------------------------------------------------------------
_ST_AVAILABLE = False
_model_cache = None
try:
    from sentence_transformers import SentenceTransformer
    _ST_AVAILABLE = True
except ImportError:
    SentenceTransformer = None  # type: ignore[assignment,misc]

_CHROMA_AVAILABLE = False
try:
    import chromadb
    _CHROMA_AVAILABLE = True
except ImportError:
    chromadb = None  # type: ignore[assignment]

# HF Hub authentication (optional)
try:
    import os as _os
    try:
        from dotenv import load_dotenv as _load_dotenv
        _load_dotenv()
    except ImportError:
        pass
    _hf_token = _os.environ.get("HF_TOKEN")
    if _hf_token:
        _hf_token = _hf_token.strip()
        from huggingface_hub import login as _hf_login
        _hf_login(token=_hf_token, add_to_git_credential=False)
        logger.info("Authenticated with Hugging Face Hub.")
except Exception:
    pass

TOKEN_RE = re.compile(r"[a-zA-Z]{3,}")

# ---------------------------------------------------------------------------
# ChromaDB path  (backend/data/chroma_db/)
# ---------------------------------------------------------------------------
_CHROMA_DIR = Path(__file__).resolve().parents[3] / "data" / "chroma_db"
_COLLECTION_NAME = "journal_cfps"

# ---------------------------------------------------------------------------
# Domain keywords (unchanged from V1)
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
# JournalFinder (ChromaDB-backed)
# ---------------------------------------------------------------------------

class JournalFinder:
    """
    Journal recommender powered by ChromaDB + SentenceTransformer.

    On ``__init__``, connects to the persistent ChromaDB at
    ``backend/data/chroma_db/`` and loads the ``journal_cfps``
    collection.  If the DB is missing / empty, ``recommend()`` returns
    ``[]`` without crashing.
    """

    _MODEL_CANDIDATES = [
        "all-MiniLM-L6-v2",                       # same as db_builder
        "allenai/specter2_base",
        "sentence-transformers/all-MiniLM-L6-v2",
    ]

    def __init__(self, use_ml: bool = True) -> None:
        self._model = None
        self._collection = None
        self._use_ml = use_ml and _ST_AVAILABLE

        # Connect to ChromaDB
        if _CHROMA_AVAILABLE and _CHROMA_DIR.exists():
            try:
                client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
                self._collection = client.get_collection(_COLLECTION_NAME)
                count = self._collection.count()
                logger.info(
                    "ChromaDB collection '%s' loaded (%d docs).",
                    _COLLECTION_NAME, count,
                )
            except Exception as exc:
                logger.warning("ChromaDB init failed: %s", exc)
                self._collection = None
        else:
            logger.warning(
                "ChromaDB not available or data dir missing (%s). "
                "Run `python -m crawler.run` to seed the database.",
                _CHROMA_DIR,
            )

        # Load embedding model
        if self._use_ml:
            self._load_model()

    def _load_model(self) -> None:
        global _model_cache
        if _model_cache is not None:
            self._model = _model_cache
            return
        for name in self._MODEL_CANDIDATES:
            for local_only in (False, True):
                try:
                    mode = "local-cache" if local_only else "online"
                    logger.info("Loading model %s (%s) ...", name, mode)
                    self._model = SentenceTransformer(
                        name, trust_remote_code=False, local_files_only=local_only,
                    )
                    _model_cache = self._model
                    logger.info("Model %s loaded (%s).", name, mode)
                    return
                except Exception as exc:
                    logger.warning("Failed to load %s (%s): %s", name, mode, exc)
        logger.warning("No ML model available — JournalFinder disabled.")
        self._use_ml = False

    # ------------------------------------------------------------------
    # Domain detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_domains(text: str) -> list[str]:
        low = text.lower()
        return [
            d for d, kws in DOMAIN_KEYWORDS.items()
            if sum(1 for k in kws if k in low) >= 2
        ]

    @staticmethod
    def _domain_bonus(meta_domains: list[str], detected: list[str]) -> float:
        if not detected or not meta_domains:
            return 0.0
        return len(set(meta_domains) & set(detected)) * 0.05

    # ------------------------------------------------------------------
    # TF-IDF fallback (no ChromaDB)
    # ------------------------------------------------------------------

    @staticmethod
    def _vectorize(text: str) -> Counter:
        return Counter(t.lower() for t in TOKEN_RE.findall(text))

    @staticmethod
    def _cosine(v1: Counter, v2: Counter) -> float:
        dot = sum(v1[k] * v2.get(k, 0) for k in v1)
        if dot == 0:
            return 0.0
        n1 = math.sqrt(sum(x * x for x in v1.values()))
        n2 = math.sqrt(sum(x * x for x in v2.values()))
        return dot / (n1 * n2) if n1 and n2 else 0.0

    # ------------------------------------------------------------------
    # Recommend
    # ------------------------------------------------------------------

    def recommend(
        self,
        abstract: str,
        title: str | None = None,
        top_k: int = 5,
        prefer_open_access: bool = False,
        min_impact_factor: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return ranked journal / CFP recommendations from ChromaDB.

        Output dict contains keys expected by ``JournalItem`` schema:
        ``journal``, ``score``, ``reason``, ``url``, ``publisher``,
        ``domains``, ``detected_domains``, ``deadline``.
        """
        query_text = f"{title}. {abstract}" if title else abstract
        detected = self._detect_domains(query_text)

        if self._collection is None or self._collection.count() == 0:
            logger.warning("ChromaDB empty or unavailable — returning [].")
            return []

        try:
            results = self._query_chromadb(query_text, top_k=top_k * 2)
        except Exception as exc:
            logger.error("ChromaDB query failed: %s", exc, exc_info=True)
            return []

        # Rank & build output
        ranked: list[dict[str, Any]] = []
        method = "SentenceTransformer embedding" if self._use_ml else "ChromaDB cosine"

        for dist, meta, doc in results:
            # ChromaDB cosine distance → similarity
            similarity = 1.0 - dist

            meta_domains = [d.strip() for d in meta.get("domains", "").split(",") if d.strip()]
            similarity += self._domain_bonus(meta_domains, detected)

            ranked.append({
                "journal": meta.get("title", "Unknown"),
                "score": round(min(similarity, 1.0), 4),
                "reason": f"Matched via {method} similarity. {doc[:120]}...",
                "url": meta.get("url", ""),
                "publisher": meta.get("publisher", ""),
                "open_access": False,
                "impact_factor": None,
                "issn": None,
                "h_index": None,
                "review_time_weeks": None,
                "acceptance_rate": None,
                "domains": meta_domains,
                "detected_domains": detected,
                "deadline": meta.get("deadline", ""),
            })

        # Sort by score descending, take top_k
        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked[:top_k]

    def _query_chromadb(
        self, query_text: str, top_k: int = 10,
    ) -> list[tuple[float, dict[str, Any], str]]:
        """Query ChromaDB with an embedded query. Returns list of
        (distance, metadata, document) tuples."""

        if self._model is not None:
            embedding = self._model.encode([query_text], show_progress_bar=False).tolist()[0]
            result = self._collection.query(
                query_embeddings=[embedding],
                n_results=top_k,
            )
        else:
            # Fallback: use ChromaDB's built-in document query
            result = self._collection.query(
                query_texts=[query_text],
                n_results=top_k,
            )

        distances = result.get("distances", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        documents = result.get("documents", [[]])[0]

        return list(zip(distances, metadatas, documents))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_ml_enabled(self) -> bool:
        return self._use_ml and self._model is not None

    @property
    def model_name(self) -> str:
        if self._model is not None:
            return getattr(self._model, "model_card_text", "all-MiniLM-L6-v2")
        return "ChromaDB default"

    @property
    def collection_count(self) -> int:
        if self._collection is not None:
            try:
                return self._collection.count()
            except Exception:
                return 0
        return 0


# Singleton
journal_finder = JournalFinder(use_ml=True)
