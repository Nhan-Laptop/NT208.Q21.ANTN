"""
Shared Document Cache — pass-by-reference storage for long text.

Provides a central in-memory cache so both the LLM routing layer and
the heuristic fallback engine can resolve ``document_id`` references
without tight coupling.

Architecture note (2026-04-03):
    Document IDs are scoped to the current server process lifetime.
    There is no cross-process or persistent caching.  Future work may
    add Redis-backed references for horizontal scaling.

    Current-turn-only scoping is the safe-first behaviour.
    Conversational document carry-forward across turns is explicitly
    deferred to a future iteration.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── In-memory cache policy (safe-first defaults) ───────────────────────
_CACHE_TTL_SECONDS = 15 * 60
_CACHE_MAX_ENTRIES = 256


@dataclass(slots=True)
class _CacheEntry:
    text: str
    created_at: float
    expires_at: float


# ── In-memory cache ─────────────────────────────────────────────────────
_DOCUMENT_CACHE: dict[str, _CacheEntry] = {}
_CACHE_LOCK = threading.RLock()

# ── Regex patterns (public — used by both LLM service and fallback) ─────
ATTACHED_DOCUMENT_RE = re.compile(
    r"<Attached_Document[^>]*>\s*(?P<text>.*?)\s*</Attached_Document>",
    re.IGNORECASE | re.DOTALL,
)

DOCUMENT_METADATA_RE = re.compile(
    r"\[Attached Document metadata:\s*document_id='(?P<document_id>[^']+)',\s*"
    r"length=(?P<length>\d+)\s+chars\.\s*DO NOT copy text\.\s*Use this "
    r"document_id in your tools\.\]",
    re.IGNORECASE,
)

_ROUTER_DOCUMENT_QUERY_FALLBACK = (
    "Người dùng đã cung cấp một tài liệu đã được cache. Hãy chọn tool phù hợp "
    "và chỉ truyền document_id."
)


def _evict_expired_locked(now_ts: float) -> None:
    expired_ids = [
        doc_id
        for doc_id, entry in _DOCUMENT_CACHE.items()
        if entry.expires_at <= now_ts
    ]
    for doc_id in expired_ids:
        _DOCUMENT_CACHE.pop(doc_id, None)

    if expired_ids:
        logger.info("Evicted %d expired cached document(s).", len(expired_ids))


def _evict_over_capacity_locked() -> None:
    if len(_DOCUMENT_CACHE) < _CACHE_MAX_ENTRIES:
        return

    # Evict oldest entries first to preserve newer request-scope references.
    overflow = len(_DOCUMENT_CACHE) - _CACHE_MAX_ENTRIES + 1
    oldest_ids = sorted(
        _DOCUMENT_CACHE,
        key=lambda doc_id: _DOCUMENT_CACHE[doc_id].created_at,
    )[:overflow]

    for doc_id in oldest_ids:
        _DOCUMENT_CACHE.pop(doc_id, None)

    logger.warning(
        "Document cache reached capacity (%d). Evicted %d oldest document(s).",
        _CACHE_MAX_ENTRIES,
        len(oldest_ids),
    )


# =========================================================================
# Public API
# =========================================================================

def store_document(text: str) -> str:
    """Store full document text in the local cache and return its ID."""
    normalized = text.strip()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    now_ts = time.time()
    expires_at = now_ts + _CACHE_TTL_SECONDS

    with _CACHE_LOCK:
        _evict_expired_locked(now_ts)
        _evict_over_capacity_locked()
        _DOCUMENT_CACHE[digest] = _CacheEntry(
            text=normalized,
            created_at=now_ts,
            expires_at=expires_at,
        )

    logger.info(
        "Cached document %s (%d chars, ttl=%ds).",
        digest,
        len(normalized),
        _CACHE_TTL_SECONDS,
    )
    return digest


def get_document(document_id: str) -> str | None:
    """Resolve a cached document ID to its full text."""
    now_ts = time.time()
    with _CACHE_LOCK:
        _evict_expired_locked(now_ts)
        entry = _DOCUMENT_CACHE.get(document_id)
        if entry is None:
            return None
        return entry.text


def extract_document_id(text: str) -> str | None:
    """Extract cached document ID from a router-facing user message."""
    match = DOCUMENT_METADATA_RE.search(text)
    if not match:
        return None
    return match.group("document_id")


def strip_document_metadata(text: str) -> str:
    """Remove router metadata so fallback logic sees only the user query."""
    without_metadata = DOCUMENT_METADATA_RE.sub("", text).strip()
    without_prefix = re.sub(
        r"^\s*User query:\s*",
        "",
        without_metadata,
        count=1,
        flags=re.IGNORECASE,
    )
    return without_prefix.strip()


def build_document_reference_prompt(
    document_id: str,
    document_text: str,
    query_text: str,
) -> str:
    """Build the metadata-only prompt that is safe to send to Groq."""
    effective_query = query_text.strip() or _ROUTER_DOCUMENT_QUERY_FALLBACK
    return (
        f"[Attached Document metadata: document_id='{document_id}', "
        f"length={len(document_text)} chars. DO NOT copy text. Use this "
        f"document_id in your tools.]\n"
        "Use only this exact document_id. Never invent or modify document IDs.\n\n"
        f"User query: {effective_query}"
    )


def restore_file_context_from_metadata(text: str) -> str | None:
    """Rebuild an Attached_Document block for local fallback paths."""
    document_id = extract_document_id(text)
    if not document_id:
        return None
    full_text = get_document(document_id)
    if not full_text:
        logger.warning(
            "Cached document %s was not found during fallback.", document_id,
        )
        return None
    return (
        f'<Attached_Document cached_document_id="{document_id}">\n'
        f"{full_text}\n"
        f"</Attached_Document>"
    )
