from __future__ import annotations

import sys
import unittest
import importlib
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI
from fastapi.dependencies import utils as fastapi_dependency_utils
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import get_db
from app.core.security import get_current_user

try:
    from .support import SyncASGIClient, TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import SyncASGIClient, TestEnvironment

fastapi_dependency_utils.check_file_field = lambda *args, **kwargs: None
auth = importlib.import_module("app.api.v1.endpoints.auth")


class AuthAIDetectionRulesApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()

        app = FastAPI()
        app.include_router(auth.router, prefix="/api/v1")

        def override_db() -> Iterator[Session]:
            db = self.env.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        def override_current_user():
            return self.user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user
        self.client = SyncASGIClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.env.close()

    def test_get_returns_default_app_rules_when_unset(self) -> None:
        response = self.client.get("/api/v1/auth/me/ai-detection-rules")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["phrases"], [])
        self.assertEqual(payload["phrase_count"], 0)
        self.assertEqual(payload["rule_source"], "default_app_rules")
        self.assertIsNone(payload["updated_at"])

    def test_put_normalizes_and_delete_resets_rules(self) -> None:
        update_response = self.client.put(
            "/api/v1/auth/me/ai-detection-rules",
            json={
                "phrases": [
                    "  as an AI language model  ",
                    "",
                    "AS AN AI LANGUAGE MODEL",
                    "it is important to note that",
                ]
            },
        )

        self.assertEqual(update_response.status_code, 200)
        updated = update_response.json()
        self.assertEqual(
            updated["phrases"],
            ["as an AI language model", "it is important to note that"],
        )
        self.assertEqual(updated["phrase_count"], 2)
        self.assertEqual(updated["rule_source"], "user_custom_rules")
        self.assertIsNotNone(updated["updated_at"])

        delete_response = self.client.delete("/api/v1/auth/me/ai-detection-rules")

        self.assertEqual(delete_response.status_code, 200)
        deleted = delete_response.json()
        self.assertEqual(deleted["phrases"], [])
        self.assertEqual(deleted["phrase_count"], 0)
        self.assertEqual(deleted["rule_source"], "default_app_rules")

    def test_put_rejects_payload_without_valid_phrases(self) -> None:
        response = self.client.put(
            "/api/v1/auth/me/ai-detection-rules",
            json={"phrases": [" ", "x"]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("at least one valid", response.json()["detail"])
