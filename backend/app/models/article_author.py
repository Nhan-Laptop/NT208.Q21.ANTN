from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin


class ArticleAuthor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "article_authors"

    article_id: Mapped[str] = mapped_column(String(36), ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    affiliation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    orcid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    author_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    article = relationship("Article", back_populates="authors")
