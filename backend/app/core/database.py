from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

try:
    from sqlalchemy.orm import DeclarativeBase
except ImportError:  # pragma: no cover - compatibility for older SQLAlchemy
    DeclarativeBase = None  # type: ignore[assignment]
    from sqlalchemy.orm import declarative_base

from app.core.config import settings


if DeclarativeBase is not None:
    class Base(DeclarativeBase):
        pass
else:  # pragma: no cover - compatibility for older SQLAlchemy
    Base = declarative_base()


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
