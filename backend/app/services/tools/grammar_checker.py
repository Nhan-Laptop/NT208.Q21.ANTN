"""
Offline Grammar & Spell Checker — powered by LanguageTool (JVM).

Uses ``language_tool_python`` which downloads and manages a local
LanguageTool Java server automatically.  No internet connection is
required after the initial setup.

Singleton pattern ensures only one JVM server is started per process.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

logger = logging.getLogger(__name__)

# ── Guard import (Java may not be installed) ────────────────────────────
try:
    import language_tool_python  # type: ignore[import-untyped]
    _LT_AVAILABLE = True
except ImportError:
    language_tool_python = None  # type: ignore[assignment]
    _LT_AVAILABLE = False
    logger.warning(
        "language_tool_python not installed — GrammarChecker disabled. "
        "Install with: pip install language_tool_python"
    )


class GrammarChecker:
    """Thread-safe singleton wrapper around LanguageTool.

    The underlying JVM server is started lazily on first use so that
    module import never blocks application startup.
    """

    _instance: GrammarChecker | None = None
    _lock = threading.Lock()

    def __new__(cls) -> GrammarChecker:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._tool = None  # type: ignore[attr-defined]
                    cls._instance._init_error: str | None = None  # type: ignore[attr-defined]
        return cls._instance

    # ------------------------------------------------------------------ #
    # Lazy initialisation
    # ------------------------------------------------------------------ #

    def _ensure_tool(self) -> bool:
        """Start the LanguageTool JVM server if it hasn't been started yet.

        Returns ``True`` if the tool is ready, ``False`` otherwise.
        """
        if self._tool is not None:
            return True
        if not _LT_AVAILABLE:
            self._init_error = "language_tool_python package is not installed."
            return False

        with self._lock:
            # Double-check after acquiring lock
            if self._tool is not None:
                return True
            try:
                logger.info("Starting LanguageTool JVM server (first use) …")
                self._tool = language_tool_python.LanguageTool("en-US")
                logger.info("LanguageTool JVM server ready.")
                return True
            except Exception as exc:
                self._init_error = str(exc)
                logger.error(
                    "Failed to start LanguageTool: %s", exc, exc_info=True,
                )
                return False

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def check_grammar(self, text: str) -> dict[str, Any]:
        """Check *text* for grammar / spelling issues.

        Returns a JSON-serializable dict::

            {
                "total_errors": 5,
                "issues": [
                    {
                        "rule_id": "MORFOLOGIK_RULE_EN_US",
                        "message": "Possible spelling mistake found.",
                        "offset": 42,
                        "length": 7,
                        "replacements": ["example", "examples"],
                        "category": "TYPOS",
                        "context": "…surrounding text…",
                    },
                    …
                ],
                "corrected_text": "The fully corrected text.",
            }

        If LanguageTool is unavailable, returns a minimal dict with
        ``total_errors: -1`` and a descriptive ``error`` key.
        """
        if not self._ensure_tool():
            return {
                "total_errors": -1,
                "issues": [],
                "corrected_text": text,
                "error": self._init_error or "LanguageTool unavailable.",
            }

        try:
            matches = self._tool.check(text)  # type: ignore[union-attr]
            corrected, decisions = self._build_safe_corrected_text(text, matches)

            issues: list[dict[str, Any]] = []
            applied_count = 0
            skipped_count = 0
            for idx, m in enumerate(matches):
                decision = decisions[idx]
                if decision["auto_applied"]:
                    applied_count += 1
                else:
                    skipped_count += 1
                issues.append({
                    "rule_id": getattr(m, "ruleId", None) or getattr(m, "rule_id", "UNKNOWN"),
                    "message": m.message,
                    "offset": m.offset,
                    "length": getattr(m, "errorLength", None) or getattr(m, "error_length", 0),
                    "replacements": (m.replacements or [])[:5],  # cap to avoid huge payloads
                    "category": self._extract_category_label(m),
                    "context": getattr(m, "context", None),
                    "auto_applied": decision["auto_applied"],
                    "autocorrect_reason": decision["reason"],
                })

            # Keep full issue details for persistence/frontend. The model-facing
            # compact summary is handled separately in llm_service budgeting.
            return {
                "total_errors": len(issues),
                "issues": issues,
                "corrected_text": corrected,
                "autocorrect_applied": applied_count,
                "autocorrect_skipped": skipped_count,
            }

        except Exception as exc:
            logger.error("GrammarChecker.check_grammar failed: %s", exc, exc_info=True)
            return {
                "total_errors": -1,
                "issues": [],
                "corrected_text": text,
                "error": str(exc),
            }

    # ------------------------------------------------------------------ #
    # Safe auto-correction helpers
    # ------------------------------------------------------------------ #

    _SAFE_CATEGORY_MARKERS = {
        "TYPOS",
        "TYPO",
        "MISSPELLING",
        "PUNCTUATION",
        "CASING",
        "GRAMMAR",
    }
    _UNSAFE_CATEGORY_MARKERS = {
        "STYLE",
        "REDUNDANCY",
        "CLARITY",
        "READABILITY",
        "SEMANTIC",
        "PARAPHRASE",
    }
    _SAFE_RULE_PREFIXES = (
        "MORFOLOGIK",
        "EN_A_VS_AN",
        "UPPERCASE",
        "LOWERCASE",
        "WHITESPACE",
        "COMMA",
        "PUNCTUATION",
        "EN_UNPAIRED_BRACKETS",
    )
    _UNSAFE_RULE_MARKERS = (
        "STYLE",
        "WORDINESS",
        "REDUNDANCY",
        "READABILITY",
        "COLLOQUIAL",
        "SIMPL",
        "PLEONASM",
    )
    _DOI_LIKE_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
    _IDENTIFIER_RE = re.compile(r"[A-Za-z]*\d+[A-Za-z0-9_\-./]*")
    _ACRONYM_RE = re.compile(r"\b[A-Z]{2,}(?:[A-Z0-9\-]*)\b")
    _TAXONOMIC_SUFFIX_RE = re.compile(
        r"(idae|inae|aceae|ales|iformes|phyta|mycetes|genus|species)$",
        re.IGNORECASE,
    )
    _BINOMIAL_RE = re.compile(r"\b[A-Z][a-z]{2,}\s+[a-z]{2,}\b")

    @classmethod
    def _extract_category_label(cls, match: Any) -> str | None:
        category = getattr(match, "category", None)
        if category is None:
            return None
        if isinstance(category, str):
            return category
        cat_id = getattr(category, "id", None)
        if isinstance(cat_id, str):
            return cat_id
        cat_name = getattr(category, "name", None)
        if isinstance(cat_name, str):
            return cat_name
        return str(category)

    @staticmethod
    def _bounded_edit_distance(a: str, b: str, cap: int = 3) -> int:
        """Compute edit distance with early exit once distance exceeds *cap*."""
        if a == b:
            return 0
        if abs(len(a) - len(b)) > cap:
            return cap + 1
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, start=1):
            cur = [i]
            min_row = i
            for j, cb in enumerate(b, start=1):
                cost = 0 if ca == cb else 1
                value = min(
                    prev[j] + 1,
                    cur[j - 1] + 1,
                    prev[j - 1] + cost,
                )
                cur.append(value)
                if value < min_row:
                    min_row = value
            if min_row > cap:
                return cap + 1
            prev = cur
        return prev[-1]

    @classmethod
    def _looks_sensitive_span(cls, text: str, offset: int, length: int) -> bool:
        span = text[offset: offset + length]
        context = text[max(0, offset - 20): min(len(text), offset + length + 20)]
        token = span.strip()

        if not token:
            return False
        if cls._DOI_LIKE_RE.search(token) or cls._DOI_LIKE_RE.search(context):
            return True
        if cls._IDENTIFIER_RE.search(token):
            return True
        if cls._ACRONYM_RE.search(token):
            return True
        if cls._BINOMIAL_RE.search(context):
            return True

        token_words = re.findall(r"[A-Za-z][A-Za-z\-]*", token)
        if any(cls._TAXONOMIC_SUFFIX_RE.search(w) for w in token_words):
            return True

        # Protect many proper nouns and scientific capitalized terms.
        if any(w and w[0].isupper() and w[1:].islower() and len(w) >= 6 for w in token_words):
            return True

        return False

    @classmethod
    def _is_safe_rule_or_category(cls, rule_id: str, category: str) -> bool:
        rule_up = rule_id.upper()
        cat_up = category.upper()
        if any(marker in cat_up for marker in cls._UNSAFE_CATEGORY_MARKERS):
            return False
        if any(marker in rule_up for marker in cls._UNSAFE_RULE_MARKERS):
            return False
        if any(rule_up.startswith(prefix) for prefix in cls._SAFE_RULE_PREFIXES):
            return True
        return any(marker in cat_up for marker in cls._SAFE_CATEGORY_MARKERS)

    @classmethod
    def _assess_autocorrect(
        cls,
        text: str,
        match: Any,
    ) -> dict[str, Any]:
        rule_id = str(getattr(match, "ruleId", None) or getattr(match, "rule_id", "UNKNOWN"))
        category = cls._extract_category_label(match) or "UNKNOWN"
        replacements = list(getattr(match, "replacements", []) or [])
        offset = int(getattr(match, "offset", 0) or 0)
        length = int(getattr(match, "errorLength", None) or getattr(match, "error_length", 0) or 0)

        if not replacements:
            return {"auto_applied": False, "reason": "no_replacement", "replacement": None, "offset": offset, "length": length}
        if offset < 0 or length <= 0 or (offset + length) > len(text):
            return {"auto_applied": False, "reason": "invalid_span", "replacement": None, "offset": offset, "length": length}
        if not cls._is_safe_rule_or_category(rule_id, category):
            return {"auto_applied": False, "reason": "unsafe_rule_category", "replacement": None, "offset": offset, "length": length}
        if cls._looks_sensitive_span(text, offset, length):
            return {"auto_applied": False, "reason": "sensitive_span", "replacement": None, "offset": offset, "length": length}

        replacement = str(replacements[0]).strip()
        if not replacement:
            return {"auto_applied": False, "reason": "empty_replacement", "replacement": None, "offset": offset, "length": length}

        original = text[offset: offset + length]
        orig_words = re.findall(r"[A-Za-z]+", original)
        repl_words = re.findall(r"[A-Za-z]+", replacement)
        rule_up = rule_id.upper()

        # Avoid style rewrites that collapse or paraphrase whole phrases.
        if len(orig_words) >= 2 and len(repl_words) <= 1 and "A_VS_AN" not in rule_up:
            return {"auto_applied": False, "reason": "phrase_rewrite_risk", "replacement": None, "offset": offset, "length": length}
        if len(orig_words) == 1 and len(repl_words) == 1:
            orig_token = orig_words[0]
            repl_token = repl_words[0]
            if orig_token.lower().endswith(repl_token.lower()) and (len(orig_token) - len(repl_token)) >= 2:
                return {"auto_applied": False, "reason": "prefix_drop_risk", "replacement": None, "offset": offset, "length": length}
            if cls._bounded_edit_distance(orig_token.lower(), repl_token.lower(), cap=2) > 2:
                return {"auto_applied": False, "reason": "large_lexical_change", "replacement": None, "offset": offset, "length": length}

        return {
            "auto_applied": True,
            "reason": "safe_autocorrect",
            "replacement": replacement,
            "offset": offset,
            "length": length,
        }

    @classmethod
    def _build_safe_corrected_text(
        cls,
        text: str,
        matches: list[Any],
    ) -> tuple[str, list[dict[str, Any]]]:
        decisions = [cls._assess_autocorrect(text, m) for m in matches]
        edits = [
            d for d in decisions
            if d["auto_applied"] and isinstance(d["replacement"], str)
        ]
        edits.sort(key=lambda d: int(d["offset"]))

        if not edits:
            return text, decisions

        chunks: list[str] = []
        cursor = 0
        for edit in edits:
            offset = int(edit["offset"])
            length = int(edit["length"])
            replacement = str(edit["replacement"])
            if offset < cursor:
                edit["auto_applied"] = False
                edit["reason"] = "overlap_skipped"
                continue
            chunks.append(text[cursor:offset])
            chunks.append(replacement)
            cursor = offset + length

        chunks.append(text[cursor:])
        return "".join(chunks), decisions

    def close(self) -> None:
        """Shut down the JVM server (called during app shutdown)."""
        if self._tool is not None:
            try:
                self._tool.close()
                logger.info("LanguageTool JVM server shut down.")
            except Exception:
                logger.warning("Error shutting down LanguageTool.", exc_info=True)
            self._tool = None


# Module-level singleton
grammar_checker = GrammarChecker()
