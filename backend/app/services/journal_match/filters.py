from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.match_request import MatchRequest


class MatchFilters:
    QUARTILE_ORDER = {"Q1": 4, "Q2": 3, "Q3": 2, "Q4": 1}

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None

    def apply(self, request: MatchRequest, candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for candidate in candidates:
            metadata = candidate.get("metadata", {})
            reasons: list[str] = []
            venue_type = str(metadata.get("venue_type") or "").lower()
            if request.desired_venue_type and request.desired_venue_type.lower() != venue_type:
                reasons.append("venue_type_mismatch")
            if request.require_scopus and not bool(metadata.get("indexed_scopus")):
                reasons.append("missing_scopus")
            if request.require_wos and not bool(metadata.get("indexed_wos")):
                reasons.append("missing_wos")
            if request.min_quartile:
                target = self.QUARTILE_ORDER.get(request.min_quartile.upper(), 0)
                actual = self.QUARTILE_ORDER.get(str(metadata.get("sjr_quartile") or metadata.get("jcr_quartile") or "").upper(), 0)
                if target:
                    if not actual:
                        reasons.append("missing_quartile")
                    elif actual < target:
                        reasons.append("quartile_below_target")
            if request.apc_budget_usd is not None and metadata.get("apc_usd") is not None:
                try:
                    if float(metadata["apc_usd"]) > float(request.apc_budget_usd):
                        reasons.append("apc_over_budget")
                except (TypeError, ValueError):
                    pass
            if request.max_review_weeks is not None and metadata.get("avg_review_weeks") is not None:
                try:
                    if float(metadata["avg_review_weeks"]) > float(request.max_review_weeks):
                        reasons.append("review_time_too_long")
                except (TypeError, ValueError):
                    pass
            deadline = self._parse_datetime(metadata.get("full_paper_deadline") or metadata.get("abstract_deadline"))
            if metadata.get("entity_type") == "cfp" and deadline and deadline < now:
                reasons.append("deadline_expired")
            if reasons:
                rejected.append({"record_id": candidate.get("record_id"), "reasons": reasons})
                continue
            accepted.append(candidate)
        diagnostics = {
            "retrieved_count": len(candidates),
            "accepted_count": len(accepted),
            "rejected": rejected,
        }
        return accepted, diagnostics


match_filters = MatchFilters()
