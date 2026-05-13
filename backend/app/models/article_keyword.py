from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin


class ArticleKeyword(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "article_keywords"
    __table_args__ = (UniqueConstraint("article_id", "normalized_keyword", name="uq_article_keyword_normalized"),)

    article_id: Mapped[str] = mapped_column(String(36), ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_keyword: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    article = relationship("Article", back_populates="keywords")
