from __future__ import annotations

import sys
import unittest
from pathlib import Path

from app.models.user import UserRole

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

try:
    from .support import TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import TestEnvironment


def _compiled_phrase_rule(name: str = "Generic academic phrasing") -> dict:
    return {
        "name": name,
        "description": "Flags generic academic transition phrases.",
        "rule_type": "phrase",
        "severity": "medium",
        "weight": 0.4,
        "conditions": [
            {
                "kind": "phrase_group",
                "phrases": ["it is important to note that", "plays a crucial role"],
                "threshold": 1,
                "scope": "paragraph",
            }
        ],
        "operator": "OR",
        "action": {"flag": True, "message": "Generic phrasing detected."},
    }


def _compiled_single_phrase_rule(name: str, phrase: str) -> dict:
    return {
        "name": name,
        "description": f"Flags phrase: {phrase}",
        "rule_type": "phrase",
        "severity": "medium",
        "weight": 0.35,
        "conditions": [
            {
                "kind": "phrase",
                "phrase": phrase,
                "phrases": [phrase],
                "threshold": 1,
                "scope": "paragraph",
            }
        ],
        "operator": "OR",
        "action": {"flag": True, "message": f"Matched phrase: {phrase}"},
    }


class AIDetectionApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()
        self.other_user = self.env.create_user(email="other-user@example.com")
        self.admin = self.env.create_user(role=UserRole.ADMIN)
        self.user_client = self.env.api_client(current_user=self.user)
        self.other_user_client = self.env.api_client(current_user=self.other_user)
        self.admin_client = self.env.api_client(current_user=self.admin)

    def tearDown(self) -> None:
        self.user_client.close()
        self.other_user_client.close()
        self.admin_client.close()
        self.env.close()

    def test_user_can_create_list_and_analyze_with_custom_rules(self) -> None:
        create_response = self.user_client.post(
            "/api/v1/ai-detection/rules",
            json={
                "source_text": "Flag generic academic phrasing.",
                "compiled_rule": _compiled_phrase_rule(),
                "scope": "user",
                "enabled": True,
            },
        )

        self.assertEqual(create_response.status_code, 201)
        created_rule = create_response.json()
        self.assertEqual(created_rule["name"], "Generic academic phrasing")

        list_response = self.user_client.get("/api/v1/ai-detection/rules")
        self.assertEqual(list_response.status_code, 200)
        listed_rules = list_response.json()["rules"]
        self.assertEqual(len(listed_rules), 1)
        self.assertEqual(listed_rules[0]["id"], created_rule["id"])

        analyze_response = self.user_client.post(
            "/api/v1/ai-detection/analyze",
            json={
                "text": "It is important to note that this paragraph plays a crucial role in the discussion.",
                "mode": "rule_only",
                "use_custom_rules": True,
                "include_explanation": False,
            },
        )
        self.assertEqual(analyze_response.status_code, 200)
        payload = analyze_response.json()
        self.assertEqual(payload["type"], "ai_detection")
        self.assertIn("final_score", payload)
        self.assertIn("matched_rules", payload)
        self.assertGreater(len(payload["matched_rules"]), 0)

    def test_non_admin_cannot_create_global_rule(self) -> None:
        response = self.user_client.post(
            "/api/v1/ai-detection/rules",
            json={
                "source_text": "Create a global rule.",
                "compiled_rule": _compiled_phrase_rule("Global rule"),
                "scope": "global",
                "enabled": True,
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_user_only_sees_owned_and_global_rules(self) -> None:
        own_rule = self.user_client.post(
            "/api/v1/ai-detection/rules",
            json={
                "source_text": "User owned rule.",
                "compiled_rule": _compiled_single_phrase_rule("User owned rule", "owned phrase"),
                "scope": "user",
                "enabled": True,
            },
        )
        self.assertEqual(own_rule.status_code, 201)

        foreign_rule = self.other_user_client.post(
            "/api/v1/ai-detection/rules",
            json={
                "source_text": "Foreign rule.",
                "compiled_rule": _compiled_single_phrase_rule("Foreign rule", "foreign phrase"),
                "scope": "user",
                "enabled": True,
            },
        )
        self.assertEqual(foreign_rule.status_code, 201)

        global_rule = self.admin_client.post(
            "/api/v1/ai-detection/rules",
            json={
                "source_text": "Global rule.",
                "compiled_rule": _compiled_single_phrase_rule("Global rule", "global phrase"),
                "scope": "global",
                "enabled": True,
            },
        )
        self.assertEqual(global_rule.status_code, 201)

        list_response = self.user_client.get("/api/v1/ai-detection/rules")
        self.assertEqual(list_response.status_code, 200)
        names = [rule["name"] for rule in list_response.json()["rules"]]
        self.assertIn("User owned rule", names)
        self.assertIn("Global rule", names)
        self.assertNotIn("Foreign rule", names)

    def test_owner_can_update_and_delete_own_rule(self) -> None:
        create_response = self.user_client.post(
            "/api/v1/ai-detection/rules",
            json={
                "source_text": "Owner rule.",
                "compiled_rule": _compiled_single_phrase_rule("Owner rule", "owner phrase"),
                "scope": "user",
                "enabled": True,
            },
        )
        self.assertEqual(create_response.status_code, 201)
        rule_id = create_response.json()["id"]

        update_response = self.user_client.patch(
            f"/api/v1/ai-detection/rules/{rule_id}",
            json={"name": "Owner rule updated", "enabled": False},
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["name"], "Owner rule updated")
        self.assertFalse(update_response.json()["enabled"])

        delete_response = self.user_client.delete(f"/api/v1/ai-detection/rules/{rule_id}")
        self.assertEqual(delete_response.status_code, 204)

        list_response = self.user_client.get("/api/v1/ai-detection/rules")
        self.assertEqual(list_response.status_code, 200)
        names = [rule["name"] for rule in list_response.json()["rules"]]
        self.assertNotIn("Owner rule updated", names)

    def test_non_owner_cannot_update_or_delete_another_users_rule(self) -> None:
        create_response = self.other_user_client.post(
            "/api/v1/ai-detection/rules",
            json={
                "source_text": "Foreign rule.",
                "compiled_rule": _compiled_single_phrase_rule("Foreign rule", "foreign phrase"),
                "scope": "user",
                "enabled": True,
            },
        )
        self.assertEqual(create_response.status_code, 201)
        rule_id = create_response.json()["id"]

        update_response = self.user_client.patch(
            f"/api/v1/ai-detection/rules/{rule_id}",
            json={"name": "Attempted takeover"},
        )
        self.assertEqual(update_response.status_code, 403)

        delete_response = self.user_client.delete(f"/api/v1/ai-detection/rules/{rule_id}")
        self.assertEqual(delete_response.status_code, 403)

    def test_admin_global_rule_is_visible_to_regular_users(self) -> None:
        create_response = self.admin_client.post(
            "/api/v1/ai-detection/rules",
            json={
                "source_text": "Create a global rule.",
                "compiled_rule": _compiled_phrase_rule("Global rule"),
                "scope": "global",
                "enabled": True,
            },
        )
        self.assertEqual(create_response.status_code, 201)

        list_response = self.user_client.get("/api/v1/ai-detection/rules")
        self.assertEqual(list_response.status_code, 200)
        names = [rule["name"] for rule in list_response.json()["rules"]]
        self.assertIn("Global rule", names)

    def test_non_admin_cannot_update_or_delete_global_rule(self) -> None:
        create_response = self.admin_client.post(
            "/api/v1/ai-detection/rules",
            json={
                "source_text": "Create a global rule.",
                "compiled_rule": _compiled_single_phrase_rule("Global rule", "global phrase"),
                "scope": "global",
                "enabled": True,
            },
        )
        self.assertEqual(create_response.status_code, 201)
        rule_id = create_response.json()["id"]

        update_response = self.user_client.patch(
            f"/api/v1/ai-detection/rules/{rule_id}",
            json={"name": "Hijacked global rule"},
        )
        self.assertEqual(update_response.status_code, 403)

        delete_response = self.user_client.delete(f"/api/v1/ai-detection/rules/{rule_id}")
        self.assertEqual(delete_response.status_code, 403)

    def test_admin_can_update_global_rule(self) -> None:
        create_response = self.admin_client.post(
            "/api/v1/ai-detection/rules",
            json={
                "source_text": "Create a global rule.",
                "compiled_rule": _compiled_single_phrase_rule("Global rule", "global phrase"),
                "scope": "global",
                "enabled": True,
            },
        )
        self.assertEqual(create_response.status_code, 201)
        rule_id = create_response.json()["id"]

        update_response = self.admin_client.patch(
            f"/api/v1/ai-detection/rules/{rule_id}",
            json={"name": "Global rule updated", "enabled": False},
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["name"], "Global rule updated")
        self.assertFalse(update_response.json()["enabled"])

    def test_analyze_loads_user_rules_and_enabled_global_rules(self) -> None:
        own_rule = self.user_client.post(
            "/api/v1/ai-detection/rules",
            json={
                "source_text": "Own analyze rule.",
                "compiled_rule": _compiled_single_phrase_rule("Own analyze rule", "owned phrase"),
                "scope": "user",
                "enabled": True,
            },
        )
        self.assertEqual(own_rule.status_code, 201)

        foreign_rule = self.other_user_client.post(
            "/api/v1/ai-detection/rules",
            json={
                "source_text": "Foreign analyze rule.",
                "compiled_rule": _compiled_single_phrase_rule("Foreign analyze rule", "foreign phrase"),
                "scope": "user",
                "enabled": True,
            },
        )
        self.assertEqual(foreign_rule.status_code, 201)

        global_enabled = self.admin_client.post(
            "/api/v1/ai-detection/rules",
            json={
                "source_text": "Enabled global analyze rule.",
                "compiled_rule": _compiled_single_phrase_rule("Enabled global analyze rule", "global phrase"),
                "scope": "global",
                "enabled": True,
            },
        )
        self.assertEqual(global_enabled.status_code, 201)

        global_disabled = self.admin_client.post(
            "/api/v1/ai-detection/rules",
            json={
                "source_text": "Disabled global analyze rule.",
                "compiled_rule": _compiled_single_phrase_rule("Disabled global analyze rule", "disabled phrase"),
                "scope": "global",
                "enabled": False,
            },
        )
        self.assertEqual(global_disabled.status_code, 201)

        analyze_response = self.user_client.post(
            "/api/v1/ai-detection/analyze",
            json={
                "text": (
                    "Owned phrase appears here. "
                    "Global phrase appears here as well. "
                    "Foreign phrase should not match because it belongs to another user. "
                    "Disabled phrase should not match because the global rule is disabled."
                ),
                "mode": "rule_only",
                "use_custom_rules": True,
                "include_explanation": False,
            },
        )
        self.assertEqual(analyze_response.status_code, 200)
        matched_names = [
            item["rule_name"]
            for item in analyze_response.json()["matched_rules"]
            if isinstance(item, dict)
        ]
        self.assertIn("Own analyze rule", matched_names)
        self.assertIn("Enabled global analyze rule", matched_names)
        self.assertNotIn("Foreign analyze rule", matched_names)
        self.assertNotIn("Disabled global analyze rule", matched_names)


if __name__ == "__main__":
    unittest.main()
