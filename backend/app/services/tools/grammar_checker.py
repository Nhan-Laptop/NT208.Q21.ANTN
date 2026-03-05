"""
Offline Grammar & Spell Checker — powered by LanguageTool (JVM).

Uses ``language_tool_python`` which downloads and manages a local
LanguageTool Java server automatically.  No internet connection is
required after the initial setup.

Singleton pattern ensures only one JVM server is started per process.
"""

from __future__ import annotations

import logging
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
            corrected = language_tool_python.utils.correct(text, matches)

            issues: list[dict[str, Any]] = []
            for m in matches:
                issues.append({
                    "rule_id": getattr(m, "ruleId", None) or getattr(m, "rule_id", "UNKNOWN"),
                    "message": m.message,
                    "offset": m.offset,
                    "length": getattr(m, "errorLength", None) or getattr(m, "error_length", 0),
                    "replacements": (m.replacements or [])[:5],  # cap to avoid huge payloads
                    "category": getattr(m, "category", None),
                    "context": getattr(m, "context", None),
                })

            return {
                "total_errors": len(issues),
                "issues": issues,
                "corrected_text": corrected,
            }

        except Exception as exc:
            logger.error("GrammarChecker.check_grammar failed: %s", exc, exc_info=True)
            return {
                "total_errors": -1,
                "issues": [],
                "corrected_text": text,
                "error": str(exc),
            }

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
