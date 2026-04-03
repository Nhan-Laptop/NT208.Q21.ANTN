"""
Database Builder — ingest scraped CFP records into a persistent ChromaDB
vector store using SentenceTransformer embeddings.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Resolve path: backend/data/chroma_db/  (relative to this file)
_CHROMA_DIR = Path(__file__).resolve().parent.parent / "data" / "chroma_db"
_COLLECTION_NAME = "journal_cfps"
_EMBED_MODEL = "allenai/specter2_base"


def _make_id(record: dict[str, Any]) -> str:
    """Deterministic ID from URL or title (MD5 hex digest)."""
    key = record.get("url") or record.get("title", "")
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def seed_database(data: list[dict[str, Any]]) -> int:
    """Seed (or fully replace) the ChromaDB ``journal_cfps`` collection.

    Parameters
    ----------
    data:
        List of CFP dicts with keys: title, scope, url, publisher,
        deadline, domains.

    Returns
    -------
    int
        Number of documents upserted.
    """
    import chromadb
    from sentence_transformers import SentenceTransformer

    _CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(_CHROMA_DIR))

    # Delete existing collection to prevent stale duplicates on re-runs
    try:
        client.delete_collection(_COLLECTION_NAME)
        logger.info("Cleared existing '%s' collection.", _COLLECTION_NAME)
    except Exception:
        pass  # collection may not exist yet

    collection = client.get_or_create_collection(
        name=_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    if not data:
        logger.warning("No data provided — collection is empty.")
        return 0

    # Embed title + scope
    model = SentenceTransformer(_EMBED_MODEL)
    texts = [
        f"{r.get('title', '')}. {r.get('scope', '')}" for r in data
    ]
    embeddings = model.encode(texts, show_progress_bar=False).tolist()

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []
    embeds: list[list[float]] = []

    seen_ids: set[str] = set()

    for record, text, emb in zip(data, texts, embeddings):
        doc_id = _make_id(record)
        if doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)

        ids.append(doc_id)
        documents.append(text)
        embeds.append(emb)
        metadatas.append({
            "publisher": record.get("publisher", ""),
            "title": record.get("title", ""),
            "url": record.get("url", ""),
            "deadline": record.get("deadline", ""),
            "domains": ",".join(record.get("domains", [])),
        })

    # Upsert in batches (ChromaDB limit = 5461 per call)
    batch_size = 5000
    for i in range(0, len(ids), batch_size):
        collection.upsert(
            ids=ids[i : i + batch_size],
            documents=documents[i : i + batch_size],
            embeddings=embeds[i : i + batch_size],
            metadatas=metadatas[i : i + batch_size],
        )

    logger.info(
        "Upserted %d document(s) into '%s'.", len(ids), _COLLECTION_NAME,
    )
    return len(ids)
