from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
import os
import asyncio

from fastapi import FastAPI
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("HF_HOME", "/tmp/aira-hf-home")
os.environ.setdefault("HF_HUB_CACHE", "/tmp/aira-hf-home/hub")
os.environ.setdefault("TRANSFORMERS_CACHE", "/tmp/aira-hf-home/transformers")

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models.chat_session import ChatSession, SessionMode
from app.models.user import User, UserRole
from app.services.embeddings.specter2_service import specter2_service
from app.services.ingestion.index_service import academic_index_service


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


class BackendTestCase(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.temp_path = Path(self.tmpdir.name)
        self.db_path = self.temp_path / "test.sqlite3"
        self.chroma_path = self.temp_path / "chroma"
        self.storage_path = self.temp_path / "storage"

        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        self._orig_database_url = settings.database_url
        self._orig_chroma_db_path = settings.chroma_db_path
        self._orig_local_storage_path = settings.local_storage_path
        self._orig_academic_seed_path = settings.academic_seed_path
        object.__setattr__(settings, "database_url", f"sqlite:///{self.db_path}")
        object.__setattr__(settings, "chroma_db_path", str(self.chroma_path))
        object.__setattr__(settings, "local_storage_path", str(self.storage_path))
        object.__setattr__(settings, "academic_seed_path", str(BACKEND_ROOT / "tests" / "fixtures" / "academic_seed.json"))
        self.addCleanup(object.__setattr__, settings, "database_url", self._orig_database_url)
        self.addCleanup(object.__setattr__, settings, "chroma_db_path", self._orig_chroma_db_path)
        self.addCleanup(object.__setattr__, settings, "local_storage_path", self._orig_local_storage_path)
        self.addCleanup(object.__setattr__, settings, "academic_seed_path", self._orig_academic_seed_path)

        academic_index_service._client = None
        self.addCleanup(setattr, academic_index_service, "_client", None)

    def db(self):
        return self.SessionLocal()

    def create_user(self, email: str = "user@example.com", role: UserRole = UserRole.ADMIN) -> User:
        db = self.db()
        try:
            user = User(email=email, full_name="Test User", hashed_password="hashed", role=role)
            db.add(user)
            db.commit()
            db.refresh(user)
            db.expunge(user)
            return user
        finally:
            db.close()

    def create_session(self, user_id: str, mode: SessionMode = SessionMode.GENERAL_QA) -> ChatSession:
        db = self.db()
        try:
            session = ChatSession(user_id=user_id, title="Test Session", mode=mode)
            db.add(session)
            db.commit()
            db.refresh(session)
            db.expunge(session)
            return session
        finally:
            db.close()

    def build_client(self, *routers, current_user: User | None = None) -> SyncASGIClient:
        app = FastAPI()
        for router in routers:
            app.include_router(router, prefix=settings.api_v1_str)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        def override_get_current_user():
            if current_user is None:
                raise RuntimeError("current_user override is required for test client")
            return current_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        return SyncASGIClient(app)

    def seed_bootstrap(self, user: User) -> None:
        from crawler.scheduler import crawl_scheduler

        db = self.db()
        try:
            crawl_scheduler.run_crawl_job(
                db,
                current_user=user,
                include_bootstrap=True,
                include_live_sources=False,
            )
        finally:
            db.close()

    def reset_embedding_service(self) -> None:
        specter2_service._model = None
        specter2_service._tokenizer = None
        specter2_service._backend = None
        specter2_service._loaded_model_name = None
        specter2_service._adapter_label = None
        specter2_service._load_attempted = False
