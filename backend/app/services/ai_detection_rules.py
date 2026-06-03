from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Sequence

from app.models.user import User

DEFAULT_AI_RULE_SOURCE = "default_app_rules"
USER_AI_RULE_SOURCE = "user_custom_rules"

_MAX_CUSTOM_RULE_PHRASES = 50
_MIN_CUSTOM_RULE_PHRASE_LENGTH = 2
_MAX_CUSTOM_RULE_PHRASE_LENGTH = 120
_WHITESPACE_RE = re.compile(r"\s+")


class AIDetectionRuleValidationError(ValueError):
    """Raised when user-provided AI detection rules are invalid."""


def _normalize_phrase(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value.strip())


def normalize_ai_detection_rule_phrases(phrases: Sequence[str] | None) -> list[str]:
    if not phrases:
        return []

    normalized: list[str] = []
    seen: set[str] = set()

    for raw in phrases:
        if not isinstance(raw, str):
            continue
        phrase = _normalize_phrase(raw)
        if not phrase:
            continue
        if len(phrase) < _MIN_CUSTOM_RULE_PHRASE_LENGTH:
            continue
        if len(phrase) > _MAX_CUSTOM_RULE_PHRASE_LENGTH:
            continue

        key = phrase.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(phrase)

        if len(normalized) > _MAX_CUSTOM_RULE_PHRASES:
            raise AIDetectionRuleValidationError(
                f"Custom AI rules support at most {_MAX_CUSTOM_RULE_PHRASES} phrases."
            )

    return normalized


def prepare_ai_detection_rule_phrases(phrases: Sequence[str] | None) -> list[str]:
    normalized = normalize_ai_detection_rule_phrases(phrases)
    if not normalized:
        raise AIDetectionRuleValidationError(
            "Please provide at least one valid AI detection phrase (2-120 characters)."
        )
    return normalized


def get_user_ai_detection_rule_phrases(user: User) -> list[str] | None:
    raw = getattr(user, "ai_detection_rule_prefs", None)
    if not isinstance(raw, dict):
        return None

    phrases = raw.get("phrases")
    if not isinstance(phrases, list):
        return None

    normalized = normalize_ai_detection_rule_phrases(phrases)
    return normalized or None


def get_user_ai_detection_rule_updated_at(user: User) -> datetime | None:
    raw = getattr(user, "ai_detection_rule_prefs", None)
    if not isinstance(raw, dict):
        return None

    updated_at = raw.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at.strip():
        return None

    try:
        return datetime.fromisoformat(updated_at)
    except ValueError:
        return None


def build_user_ai_detection_rule_prefs(phrases: Sequence[str]) -> dict[str, Any]:
    normalized = prepare_ai_detection_rule_phrases(phrases)
    return {
        "phrases": normalized,
        "updated_at": datetime.utcnow().isoformat(),
    }


def clear_user_ai_detection_rule_prefs(user: User) -> None:
    user.ai_detection_rule_prefs = None

