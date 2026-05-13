from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, selectinload

from app.models.article import Article
from app.models.cfp_event import CFPEvent
from app.models.venue import Venue
from app.services.academic_policy import (
    CRAWLER_DB_NO_DATA_MESSAGE,
    format_grounded_evidence,
    USER_SAFE_DATA_LABEL,
)
from app.services.tools.citation_checker import citation_checker


_ACADEMIC_DB_QUERY_RE = re.compile(
    r"("
    r"crawler\.?db|cơ\s*sở\s*dữ\s*liệu|co\s*so\s*du\s*lieu|database|db|"
    r"\b(?:papers?|articles?|records?)\b.*\b(?:database|db|about|on|related)\b|"
    r"\b(?:what|which)\s+(?:papers?|articles?|records?)\s+(?:do\s+we\s+have|are\s+in)\b|"
    r"\b(?:bài|bai|paper|article|bản\s*ghi|ban\s*ghi)\b.*\b(?:về|ve|liên\s*quan|lien\s*quan|trong)\b|"
    r"\b(?:có|co)\s+(?:bài|bai|paper|article|bản\s*ghi|ban\s*ghi)\b"
    r")",
    re.IGNORECASE,
)

_EXPLICIT_CITATION_TASK_RE = re.compile(
    r"\b("
    r"verify\s+citation|citation\s+check|reference\s+check|bibliography|"
    r"xác\s*minh\s*trích\s*dẫn|xac\s*minh\s*trich\s*dan|"
    r"kiểm\s*tra\s*(?:citation|trích\s*dẫn|tài\s*liệu\s*tham\s*khảo|doi)|"
    r"kiem\s*tra\s*(?:citation|trich\s*dan|tai\s*lieu\s*tham\s*khao|doi)"
    r")\b",
    re.IGNORECASE,
)

_RETRACTION_TASK_RE = re.compile(
    r"\b(retraction|retracted|pubpeer|rút\s*bài|rut\s*bai|thu\s*hồi|thu\s*hoi)\b",
    re.IGNORECASE,
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*", re.UNICODE)
_MARKER_RE = re.compile(
    r"("
    r"hãy|hay|cho\s+tôi\s+biết|cho\s+toi\s+biet|các|cac|những|nhung|"
    r"bài|bai|paper|papers|article|articles|records?|bản\s*ghi|ban\s*ghi|"
    r"trong|về|ve|liên\s*quan|lien\s*quan|cơ\s*sở\s*dữ\s*liệu|co\s*so\s*du\s*lieu|"
    r"database|crawler\.?db|db|current|existing|about|on|tell\s+me|what|which|do\s+we\s+have|are\s+in"
    r")",
    re.IGNORECASE,
)
_STOPWORDS = {
    "the", "this", "that", "these", "those", "and", "or", "for", "with", "from",
    "into", "your", "our", "have", "has", "are", "was", "were", "in", "on",
    "about", "paper", "papers", "article", "articles", "record", "records",
    "bai", "cac", "cho", "toi", "biet", "trong", "lien", "quan", "crawler",
    "database", "db", "co", "so", "du", "lieu", "ve",
}


@dataclass(slots=True)
class AcademicQueryResult:
    text: str
    records: list[dict[str, Any]]


class AcademicQueryService:
    """Small grounded academic corpus query path for general chat.

    This is intentionally conservative: it only handles user phrasing that
    explicitly asks about records/papers/data in the local academic database.
    Citation and DOI verification remain owned by the citation tools.
    """

    def should_handle(self, text: str) -> bool:
        normalized = (text or "").strip()
        if not normalized:
            return False
        if citation_checker.extract_dois(normalized):
            return False
        if _EXPLICIT_CITATION_TASK_RE.search(normalized) or _RETRACTION_TASK_RE.search(normalized):
            return False
        return bool(_ACADEMIC_DB_QUERY_RE.search(normalized))

    def answer(self, db: Session, text: str, *, limit: int = 5) -> AcademicQueryResult:
        terms = self._extract_terms(text)
        if not terms:
            return AcademicQueryResult(text=self._no_data_text(), records=[])

        records = self._search_records(db, terms, limit=limit)
        if not records:
            return AcademicQueryResult(text=self._no_data_text(terms), records=[])

        lines = [
            f"Mình tìm thấy {len(records)} bản ghi liên quan trong {USER_SAFE_DATA_LABEL}. "
            "Các kết quả dưới đây là grounded findings từ dữ liệu học thuật hiện có, không phải kết luận từ kiến thức ngoài."
        ]
        for idx, record in enumerate(records, 1):
            title = record.get("title") or "Không có tiêu đề"
            kind = record.get("entity_type") or "record"
            snippet = str(record.get("snippet") or "").strip()
            lines.append(f"{idx}. **{title}** ({kind})")
            if snippet:
                lines.append(f"   {snippet[:280]}")
            lines.append(f"   {format_grounded_evidence(record)}")
        return AcademicQueryResult(text="\n".join(lines), records=records)

    @staticmethod
    def _extract_terms(text: str) -> list[str]:
        cleaned = _MARKER_RE.sub(" ", text or "")
        terms: list[str] = []
        seen: set[str] = set()
        for raw in _TOKEN_RE.findall(cleaned):
            term = raw.strip("._-").lower()
            if len(term) < 3 or term in _STOPWORDS:
                continue
            if term not in seen:
                seen.add(term)
                terms.append(term)
        return terms[:10]

    @staticmethod
    def _matches_blob(blob: str, terms: list[str]) -> int:
        low = blob.lower()
        return sum(1 for term in terms if term in low)

    def _search_records(self, db: Session, terms: list[str], *, limit: int) -> list[dict[str, Any]]:
        scored: list[tuple[int, dict[str, Any]]] = []

        articles = (
            db.query(Article)
            .options(selectinload(Article.venue), selectinload(Article.authors), selectinload(Article.keywords))
            .limit(500)
            .all()
        )
        for article in articles:
            keyword_text = " ".join(keyword.keyword for keyword in article.keywords)
            author_text = " ".join(author.full_name for author in article.authors)
            venue_title = article.venue.title if article.venue else None
            blob = " ".join(
                part for part in [
                    article.title,
                    article.abstract or "",
                    keyword_text,
                    author_text,
                    venue_title or "",
                    article.doi or "",
                ] if part
            )
            score = self._matches_blob(blob, terms)
            if score <= 0:
                continue
            scored.append((score, {
                "entity_type": "article",
                "title": article.title,
                "abstract": article.abstract,
                "snippet": article.abstract,
                "venue": venue_title,
                "year": article.publication_year,
                "doi": article.doi,
                "url": article.url,
                "authors": [author.full_name for author in article.authors[:5]],
            }))

        venues = (
            db.query(Venue)
            .options(selectinload(Venue.subjects))
            .limit(500)
            .all()
        )
        for venue in venues:
            subject_text = " ".join(subject.label for subject in venue.subjects)
            blob = " ".join(
                part for part in [
                    venue.title,
                    venue.canonical_title,
                    venue.publisher or "",
                    venue.aims_scope or "",
                    subject_text,
                ] if part
            )
            score = self._matches_blob(blob, terms)
            if score <= 0:
                continue
            scored.append((score, {
                "entity_type": "venue",
                "title": venue.title,
                "abstract": venue.aims_scope,
                "snippet": venue.aims_scope,
                "venue": venue.publisher,
                "year": "N/A",
                "doi": "N/A",
                "url": venue.homepage_url,
            }))

        cfps = (
            db.query(CFPEvent)
            .options(selectinload(CFPEvent.venue))
            .limit(500)
            .all()
        )
        for cfp in cfps:
            topic_text = " ".join(cfp.topic_tags or [])
            venue_title = cfp.venue.title if cfp.venue else None
            blob = " ".join(
                part for part in [
                    cfp.title,
                    cfp.description or "",
                    topic_text,
                    venue_title or "",
                    cfp.publisher or "",
                ] if part
            )
            score = self._matches_blob(blob, terms)
            if score <= 0:
                continue
            scored.append((score, {
                "entity_type": "cfp",
                "title": cfp.title,
                "abstract": cfp.description,
                "snippet": cfp.description,
                "venue": venue_title or cfp.publisher,
                "year": cfp.full_paper_deadline.isoformat() if cfp.full_paper_deadline else "N/A",
                "doi": "N/A",
                "url": cfp.source_url,
            }))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in scored[:limit]]

    @staticmethod
    def _no_data_text(terms: list[str] | None = None) -> str:
        if terms:
            return (
                f"Mình chưa tìm thấy bài hoặc bản ghi học thuật liên quan trong {USER_SAFE_DATA_LABEL}. "
                f"Từ khóa đã kiểm tra: {', '.join(terms[:6])}. "
                "Bạn có thể thử từ khóa rộng hơn/hẹp hơn, hoặc gửi DOI, tiêu đề, tác giả nếu có."
            )
        return CRAWLER_DB_NO_DATA_MESSAGE


academic_query_service = AcademicQueryService()
