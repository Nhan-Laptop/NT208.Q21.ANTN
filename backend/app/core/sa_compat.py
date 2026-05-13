from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import Column

try:
    from sqlalchemy.orm import Mapped, mapped_column
except ImportError:  # pragma: no cover - compatibility for SQLAlchemy < 2.0
    T = TypeVar("T")

    class Mapped(Generic[T]):  # type: ignore[no-redef]
        pass

    def mapped_column(*args, **kwargs):  # type: ignore[no-redef]
        return Column(*args, **kwargs)


__all__ = ["Mapped", "mapped_column"]
