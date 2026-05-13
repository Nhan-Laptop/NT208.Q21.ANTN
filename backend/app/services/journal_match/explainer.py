from __future__ import annotations

from typing import Any

from app.services.academic_policy import format_grounded_evidence


class MatchExplainer:
    @staticmethod
    def _confidence_level(score: float) -> str:
        if score >= 0.7:
            return "cao"
        if score >= 0.4:
            return "trung_binh"
        return "thap"

    def _has_grounded_recommendation_metadata(self, metadata: dict[str, Any], candidate: dict[str, Any]) -> bool:
        subject_labels = metadata.get("subject_labels") or metadata.get("topic_tags")
        if isinstance(subject_labels, str):
            has_subject = bool(subject_labels.strip())
        else:
            has_subject = bool(subject_labels)
        has_source = bool(metadata.get("provenance_sources") or metadata.get("source_details"))
        has_indexing = bool(metadata.get("embedding_model") or candidate.get("collection"))
        return bool(metadata.get("production_eligible", True) and has_subject and has_source and has_indexing)

    @staticmethod
    def _keyword_overlap(manuscript_text: str, document_text: str) -> list[str]:
        """Return overlapping meaningful tokens between manuscript and venue document."""
        import re
        manuscript_tokens = {t.lower() for t in re.findall(r"[a-zA-Z][a-zA-Z\-]{3,}", manuscript_text)}
        document_tokens = {t.lower() for t in re.findall(r"[a-zA-Z][a-zA-Z\-]{3,}", document_text)}
        stopwords = {
            "the", "and", "for", "with", "from", "that", "this", "using", "based",
            "study", "paper", "results", "method", "methods", "approach", "analysis",
            "also", "show", "shown", "include", "including", "provide", "propose",
            "present", "section", "conclusion", "introduction", "discussion",
        }
        overlap = (manuscript_tokens & document_tokens) - stopwords
        return sorted(overlap)[:10]

    def build(self, candidate: dict[str, Any], manuscript_text: str = "") -> dict[str, Any]:
        metadata = candidate.get("metadata", {})
        breakdown = candidate.get("score_breakdown", {})
        evidence_points = []
        verified_metrics = metadata.get("verified_metrics") if isinstance(metadata.get("verified_metrics"), dict) else {}
        subject_labels = metadata.get("subject_labels") or metadata.get("topic_tags") or ""

        if subject_labels:
            evidence_points.append(f"Phù hợp chủ đề: {subject_labels}")
        if metadata.get("publisher"):
            evidence_points.append(f"Nhà xuất bản: {metadata['publisher']}")
        if verified_metrics.get("sjr_quartile") or verified_metrics.get("jcr_quartile"):
            evidence_points.append(
                f"Quartile: {verified_metrics.get('sjr_quartile') or verified_metrics.get('jcr_quartile')}"
            )
        if verified_metrics.get("avg_review_weeks") is not None:
            evidence_points.append(f"Thời gian review đã ghi nhận: {verified_metrics['avg_review_weeks']} tuần")
        if metadata.get("supporting_evidence"):
            titles = [item.get("title") for item in metadata.get("supporting_evidence", []) if item.get("title")]
            if titles:
                evidence_points.append("Bài liên quan dùng làm evidence: " + "; ".join(titles[:2]))

        warning_flags = metadata.get("warning_flags")
        if isinstance(warning_flags, list) and "suspected_book_series" in warning_flags:
            evidence_points.append("Cảnh báo: đây là book series, không phải journal chính thống.")

        domain_fit = breakdown.get("domain_fit_score", 0.0)
        scope_overlap = breakdown.get("scope_overlap_score", 0.0)
        domain_reasons = breakdown.get("domain_mismatch_reasons", []) or []

        if domain_fit > 0.5:
            evidence_points.append(f"Mức khớp lĩnh vực: {domain_fit:.2f}")
        if scope_overlap > 0.05:
            keyword_match = self._keyword_overlap(manuscript_text, candidate.get("document", ""))
            if keyword_match:
                evidence_points.append("Từ khóa chung: " + ", ".join(keyword_match[:6]))

        title = metadata.get("primary_label") or metadata.get("title") or metadata.get("venue_id") or candidate.get("record_id")
        try:
            score = float(breakdown.get("final_score", candidate.get("final_score", 0.0)) or 0.0)
        except (TypeError, ValueError):
            score = 0.0

        confidence = self._confidence_level(score)

        if self._has_grounded_recommendation_metadata(metadata, candidate):
            summary = (
                f"{title} là gợi ý best-fit với điểm xếp hạng nội bộ {score:.4f} "
                f"(độ tin cậy: {confidence}), dựa trên mức khớp ngữ nghĩa "
                "và metadata venue đã truy xuất. Đây là recommendation có căn cứ, không phải đảm bảo được chấp nhận."
            )
            if domain_reasons:
                summary += f" Lưu ý: {'; '.join(domain_reasons)}."
        else:
            summary = (
                f"{title} chỉ có thể xem là candidate sơ bộ vì còn thiếu subject, provenance, source hoặc indexing metadata. "
                "Không nên diễn giải đây là recommendation đã có căn cứ."
            )

        return {
            "summary": summary,
            "confidence": confidence,
            "evidence_points": [*evidence_points, format_grounded_evidence(metadata)],
            "document_excerpt": candidate.get("document", "")[:400],
        }


match_explainer = MatchExplainer()
