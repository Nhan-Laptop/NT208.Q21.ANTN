"""
Journal Finder — intelligent journal recommendation backed by ChromaDB.

Queries a persistent ChromaDB vector store (seeded by ``backend/crawler/``)
using SentenceTransformer embeddings.  Falls back to an empty list if the
DB is missing, empty, or the embedding model is unavailable — never crashes
the chat.
"""

import logging
import re
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

# ---------------------------------------------------------------------------
# ChromaDB path  (backend/data/chroma_db/)
# ---------------------------------------------------------------------------
_CHROMA_DIR = Path(__file__).resolve().parents[3] / "data" / "chroma_db"
_COLLECTION_NAME = "journal_cfps"
_EMBED_MODEL = "allenai/specter2_base"

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

    def __init__(self, use_ml: bool = True) -> None:
        self._model = None
        self._collection = None
        self._use_ml = use_ml and _ST_AVAILABLE

        if use_ml and not _ST_AVAILABLE:
            logger.warning(
                "sentence-transformers is unavailable; %s retrieval disabled.",
                _EMBED_MODEL,
            )

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
        try:
            logger.info("Loading model %s ...", _EMBED_MODEL)
            self._model = SentenceTransformer(
                _EMBED_MODEL,
                trust_remote_code=False,
            )
            _model_cache = self._model
            logger.info("Model %s loaded.", _EMBED_MODEL)
        except Exception as exc:
            logger.warning("Failed to load %s: %s", _EMBED_MODEL, exc)
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
        method = f"{_EMBED_MODEL} embedding"

        for dist, meta, doc in results:
            meta = meta or {}
            doc = doc or ""

            raw_distance = float(dist) if dist is not None else 1.0
            base_sim = 1.0 - raw_distance
            similarity = max(0.0, min(base_sim, 1.0))

            meta_domains = [d.strip() for d in meta.get("domains", "").split(",") if d.strip()]
            similarity = max(
                0.0,
                min(similarity + self._domain_bonus(meta_domains, detected), 1.0),
            )

            ranked.append({
                "journal": meta.get("title", "Unknown"),
                "score": round(similarity, 4),
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

        if self._model is None:
            raise RuntimeError(
                f"{_EMBED_MODEL} is unavailable; cannot query ChromaDB safely.",
            )

        embedding = self._model.encode([query_text], show_progress_bar=False).tolist()[0]
        result = self._collection.query(
            query_embeddings=[embedding],
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
            return _EMBED_MODEL
        return f"{_EMBED_MODEL} (unavailable)"

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
