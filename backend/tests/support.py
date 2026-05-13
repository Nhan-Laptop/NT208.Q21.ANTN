from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import os
import asyncio
from typing import Iterator

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("HF_HOME", "/tmp/aira-hf-home")
os.environ.setdefault("HF_HUB_CACHE", "/tmp/aira-hf-home/hub")
os.environ.setdefault("TRANSFORMERS_CACHE", "/tmp/aira-hf-home/transformers")

from fastapi import FastAPI
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.endpoints import chat, crawl_admin, journal_match, manuscripts, tools, venues
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models.chat_session import ChatSession, SessionMode
from app.models.user import User, UserRole
from app.services.embeddings.specter2_service import specter2_service
from app.services.ingestion.index_service import academic_index_service

DEFAULT_SEED_PATH = (BACKEND_ROOT / "tests" / "fixtures" / "academic_seed.json").resolve()

SAMPLE_MANUSCRIPT = """Adaptive Retrieval for Scientific Knowledge Graphs

Abstract
We study scientific retrieval for interdisciplinary manuscripts combining graph retrieval, biomedical NLP,
and reliability-aware ranking. Our method aligns manuscript structure with venue scope and article exemplars.

Keywords: scientific retrieval; biomedical NLP; ranking systems; graph learning; reproducibility

1 Introduction
This manuscript explores retrieval augmented matching for academic venues. The work spans machine learning,
knowledge graphs, biomedical text mining, and operational reliability. We evaluate ranking transparency,
submission constraints, and venue policy fit.

2 Methods
We build deterministic preprocessing, vector retrieval, and grounded reranking over articles, venues, and CFPs.

References
[1] A. Author. Scientific Retrieval at Scale. doi:10.1000/xyz123
[2] B. Author. Biomedical Language Models for Discovery. doi:10.1000/xyz456
[3] C. Author. Reliable Ranking Systems. doi:10.1000/xyz789
[4] D. Author. Graph Methods in Research Infrastructure. doi:10.1000/xyz101
[5] E. Author. Transparent Venue Matching. doi:10.1000/xyz202
"""


class SyncASGIClient:
    def __init__(self, app: FastAPI) -> None:
        self._transport = httpx.ASGITransport(app=app)
        self._client = httpx.AsyncClient(transport=self._transport, base_url="http://testserver")

    def request(self, method: str, url: str, **kwargs):
        return asyncio.run(self._client.request(method, url, **kwargs))

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def close(self) -> None:
        asyncio.run(self._client.aclose())


class TestEnvironment:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "test.sqlite3"
        self.chroma_path = self.root / "chroma"
        self.cache_path = self.root / "hf-cache"
        self.master_key_path = self.root / ".aira_master_key"
        self._settings_backup = {
            "database_url": settings.database_url,
            "chroma_db_path": settings.chroma_db_path,
            "hf_cache_dir": settings.hf_cache_dir,
            "academic_seed_path": settings.academic_seed_path,
            "master_key_file": settings.master_key_file,
            "academic_enable_startup_schema_create": settings.academic_enable_startup_schema_create,
            "academic_enable_startup_source_bootstrap": settings.academic_enable_startup_source_bootstrap,
            "academic_enable_startup_chroma_init": settings.academic_enable_startup_chroma_init,
            "academic_embedding_hash_fallback": settings.academic_embedding_hash_fallback,
        }
        object.__setattr__(settings, "database_url", f"sqlite:///{self.db_path}")
        object.__setattr__(settings, "chroma_db_path", str(self.chroma_path))
        object.__setattr__(settings, "hf_cache_dir", str(self.cache_path))
        object.__setattr__(settings, "academic_seed_path", str(DEFAULT_SEED_PATH))
        object.__setattr__(settings, "master_key_file", str(self.master_key_path))
        object.__setattr__(settings, "academic_enable_startup_schema_create", False)
        object.__setattr__(settings, "academic_enable_startup_source_bootstrap", False)
        object.__setattr__(settings, "academic_enable_startup_chroma_init", False)
        object.__setattr__(settings, "academic_embedding_hash_fallback", True)
        self._user_counter = 0
        self._reset_services()
        self.engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(self.engine)

    def close(self) -> None:
        academic_index_service._client = None
        self.engine.dispose()
        for key, value in self._settings_backup.items():
            object.__setattr__(settings, key, value)
        self._reset_services()
        self._tmp.cleanup()

    def _reset_services(self) -> None:
        academic_index_service._client = None
        specter2_service._model = None
        specter2_service._tokenizer = None
        specter2_service._backend = None
        specter2_service._loaded_model_name = None
        specter2_service._adapter_label = None
        specter2_service._load_attempted = False

    def session(self) -> Session:
        return self.SessionLocal()

    def create_user(self, *, role: UserRole = UserRole.RESEARCHER, email: str | None = None) -> User:
        with self.session() as db:
            self._user_counter += 1
            user = User(
                email=email or f"{role.value}-{self._user_counter}-{self.root.name}@example.com",
                full_name="Round 2 Tester",
                hashed_password="not-used",
                role=role,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            db.expunge(user)
            return user

    def create_chat_session(self, *, user: User, mode: SessionMode = SessionMode.GENERAL_QA, title: str = "Round 2 Session") -> ChatSession:
        with self.session() as db:
            session_obj = ChatSession(user_id=user.id, mode=mode, title=title)
            db.add(session_obj)
            db.commit()
            db.refresh(session_obj)
            db.expunge(session_obj)
            return session_obj

    def api_client(self, *, current_user: User) -> SyncASGIClient:
        app = FastAPI()
        app.include_router(chat.router, prefix="/api/v1")
        app.include_router(crawl_admin.router, prefix="/api/v1")
        app.include_router(journal_match.router, prefix="/api/v1")
        app.include_router(manuscripts.router, prefix="/api/v1")
        app.include_router(tools.router, prefix="/api/v1")
        app.include_router(venues.router, prefix="/api/v1")

        def override_db() -> Iterator[Session]:
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        def override_current_user() -> User:
            return current_user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user
        return SyncASGIClient(app)
