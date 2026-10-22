"""Settings boundary, secret-free responses, explicit testing, and provider cache identity."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import lesson_builder as builder
import main
import model_settings as settings
import llm_client
from model_settings import GenerationConfig, SettingsError
from test_lesson_cache import generated_card, graph_with_routes


PUBLIC = {"provider": "api", "base_url": "https://example.invalid/v1", "model": "test-model",
          "api_format": "chat_completions", "output_mode": "json_object", "has_api_key": True,
          "revision": "synthetic-revision"}
SYNTHETIC_KEY = "sk-synthetic-not-a-real-secret"


class ModelSettingsApiTests(unittest.TestCase):
    def setUp(self):
        self.previous = main.app.state.desktop_local_only
        main.app.state.desktop_local_only = False
        self.client = TestClient(main.app, base_url="http://127.0.0.1:8123")

    def tearDown(self):
        self.client.close()
        main.app.state.desktop_local_only = self.previous

    def test_read_only_public_settings_never_runs_a_model_or_saves(self):
        with patch.object(main, "get_public_settings", return_value=PUBLIC), \
             patch.object(main, "save_settings") as save, patch.object(main, "generate_text") as model:
            result = self.client.get("/settings/model")
        self.assertEqual(200, result.status_code)
        self.assertEqual(PUBLIC, result.json())
        self.assertEqual("no-store", result.headers["Cache-Control"])
        save.assert_not_called()
        model.assert_not_called()

    def test_save_updates_config_clears_completed_cache_and_never_auto_tests(self):
        data = {key: value for key, value in PUBLIC.items() if key not in {"revision", "has_api_key"}}
        data["api_key"] = SYNTHETIC_KEY
        with patch.object(main, "save_settings", return_value=PUBLIC) as save, \
             patch.object(main, "clear_lesson_cache") as clear, patch.object(main, "generate_text") as model:
            result = self.client.post("/settings/model", json=data)
        self.assertEqual(200, result.status_code)
        self.assertNotIn(SYNTHETIC_KEY, result.text)
        self.assertNotIn("api_key", result.json())
        save.assert_called_once_with(data)
        clear.assert_called_once_with()
        model.assert_not_called()

    def test_fresh_deepseek_settings_are_readable_but_explicit_test_needs_own_key(self):
        with tempfile.TemporaryDirectory(prefix="mathpath-deepseek-api-") as directory, \
             patch.object(settings, "SETTINGS_FILE", Path(directory) / "api_settings.dpapi"), \
             patch.object(settings, "protect_bytes", side_effect=AssertionError("no key storage on reads")), \
             patch.object(llm_client, "OpenAI", side_effect=AssertionError("missing key must stop before SDK")) as sdk, \
             patch.object(llm_client, "get_usable_session", side_effect=AssertionError("no fallback to OAuth")) as oauth:
            public = self.client.get("/settings/model")
            self.assertEqual(public.status_code, 200)
            self.assertEqual(public.json()["base_url"], "https://models.sjtu.edu.cn/api/v1")
            self.assertEqual(public.json()["model"], "deepseek-reasoner")
            self.assertFalse(public.json()["has_api_key"])
            tested = self.client.post("/settings/model/test")
            self.assertEqual(tested.status_code, 503)
            self.assertIn("API 密钥", tested.json()["detail"])
            self.assertFalse(settings.SETTINGS_FILE.exists())
            sdk.assert_not_called()
            oauth.assert_not_called()

    def test_invalid_json_or_oversized_config_does_not_echo_submitted_secret(self):
        with patch.object(main, "save_settings") as save:
            invalid = self.client.post("/settings/model", content="{" + SYNTHETIC_KEY)
            large = self.client.post("/settings/model", content=(SYNTHETIC_KEY * 2000).encode())
        self.assertEqual(400, invalid.status_code)
        self.assertEqual(413, large.status_code)
        self.assertNotIn(SYNTHETIC_KEY, invalid.text + large.text)
        save.assert_not_called()

    def test_failed_save_preserves_cache_and_returns_safe_error(self):
        with patch.object(main, "save_settings", side_effect=SettingsError("模型配置格式不正确。")), \
             patch.object(main, "clear_lesson_cache") as clear:
            result = self.client.post("/settings/model", json={"api_key": SYNTHETIC_KEY})
        self.assertEqual(400, result.status_code)
        self.assertNotIn(SYNTHETIC_KEY, result.text)
        clear.assert_not_called()

    def test_foreign_origin_or_host_cannot_read_save_or_test_in_development_mode(self):
        with patch.object(main, "get_public_settings") as read, patch.object(main, "save_settings") as save, \
             patch.object(main, "generate_text") as model:
            self.assertEqual(403, self.client.get("/settings/model", headers={"Host": "untrusted.example:8123"}).status_code)
            self.assertEqual(403, self.client.post("/settings/model", headers={"Origin": "https://untrusted.example"}, json={}).status_code)
            self.assertEqual(403, self.client.post("/settings/model/test", headers={"Origin": "null"}).status_code)
        read.assert_not_called()
        save.assert_not_called()
        model.assert_not_called()

    def test_explicit_test_runs_once_and_never_echoes_model_output(self):
        with patch.object(main, "generate_text", return_value=SYNTHETIC_KEY) as model, patch.object(main, "save_settings") as save:
            result = self.client.post("/settings/model/test")
        self.assertEqual(200, result.status_code)
        self.assertIs(result.json()["ok"], True)
        self.assertNotIn(SYNTHETIC_KEY, result.text)
        self.assertEqual(1, model.call_count)
        save.assert_not_called()

    def test_status_read_never_starts_authentication(self):
        idle = {"status": "idle", "message": "本次运行尚未发起登录。", "attempt": 0}
        with patch.object(main, "get_connection_status", return_value=idle), \
             patch.object(main, "start_connection") as login, patch.object(main, "generate_text") as model:
            result = self.client.get("/settings/chatgpt/status")
        self.assertEqual(200, result.status_code)
        self.assertEqual(idle, result.json())
        self.assertEqual("no-store", result.headers["Cache-Control"])
        login.assert_not_called()
        model.assert_not_called()

    def test_explicit_login_returns_pending_without_model_or_provider_changes(self):
        pending = {"status": "pending", "message": "请在系统浏览器完成授权。", "attempt": 1}
        with patch.object(main, "start_connection", return_value=pending) as login, \
             patch.object(main, "save_settings") as save, patch.object(main, "generate_text") as model:
            result = self.client.post("/settings/chatgpt/login")
        self.assertEqual(200, result.status_code)
        self.assertEqual(pending, result.json())
        login.assert_called_once_with()
        save.assert_not_called()
        model.assert_not_called()

    def test_foreign_pages_cannot_start_authentication_or_read_status(self):
        with patch.object(main, "start_connection") as login, patch.object(main, "get_connection_status") as status:
            self.assertEqual(403, self.client.post("/settings/chatgpt/login", headers={"Origin": "https://untrusted.example"}).status_code)
            self.assertEqual(403, self.client.get("/settings/chatgpt/status", headers={"Host": "untrusted.example:8123"}).status_code)
        login.assert_not_called()
        status.assert_not_called()


class ProviderCacheTests(unittest.TestCase):
    def setUp(self):
        builder.clear_lesson_cache()
        self.addCleanup(builder.clear_lesson_cache)

    def test_cache_and_request_use_same_immutable_provider_snapshot(self):
        first = GenerationConfig(provider="api", base_url="https://a.invalid/v1", model="user-selected-model",
                                 api_format="chat_completions", output_mode="json_object", revision="revision1",
                                 api_key=SYNTHETIC_KEY)
        second = replace(first, revision="revision2", api_key="synthetic-new-key")
        third = replace(second, base_url="https://b.invalid/v1")
        graph = graph_with_routes()
        with patch.object(builder, "resolve_generation_config", return_value=first) as resolve, \
             patch.object(builder, "generate_text", return_value=json.dumps(generated_card())) as model:
            builder.build_lesson(graph, "goal")
            builder.build_lesson(graph, "goal")
            self.assertEqual(1, model.call_count)
            self.assertIs(first, model.call_args.kwargs["configuration"])
            self.assertEqual(first.model, model.call_args.kwargs["model"])
            resolve.return_value = second
            builder.build_lesson(graph, "goal")
            self.assertEqual(2, model.call_count)
            resolve.return_value = third
            builder.build_lesson(graph, "goal")
            self.assertEqual(3, model.call_count)
            self.assertIs(third, model.call_args.kwargs["configuration"])


if __name__ == "__main__":
    unittest.main()
