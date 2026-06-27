import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, Float, ForeignKey, Index, String

from app.core.database import Base
from app.core.encrypted_types import EncryptedJSON, EncryptedText
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import enum_values


class RuleType(str, Enum):
    PHRASE = "phrase"
    REGEX = "regex"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class RuleSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RuleScope(str, Enum):
    USER = "user"
    GLOBAL = "global"


class AIDetectionRule(Base):
    __tablename__ = "ai_detection_rules"
    __table_args__ = (
        Index("ix_ai_detection_rules_owner_enabled", "owner_id", "enabled"),
        Index("ix_ai_detection_rules_scope_enabled", "scope", "enabled"),
        Index("ix_ai_detection_rules_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    source_text: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    rule_type: Mapped[RuleType] = mapped_column(
        SqlEnum(RuleType, values_callable=enum_values),
        default=RuleType.HYBRID,
        nullable=False,
    )
    severity: Mapped[RuleSeverity] = mapped_column(
        SqlEnum(RuleSeverity, values_callable=enum_values),
        default=RuleSeverity.MEDIUM,
        nullable=False,
    )
    weight: Mapped[float] = mapped_column(Float, default=0.2, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scope: Mapped[RuleScope] = mapped_column(
        SqlEnum(RuleScope, values_callable=enum_values),
        default=RuleScope.USER,
        nullable=False,
    )
    rule_json: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON, nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
