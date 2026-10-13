"""API 配置的离线检查；只使用临时文件和明确的合成密钥。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import chatgpt_login
import model_settings as settings

CANARY = "synthetic-secret-must-not-appear"
FIELDS = {"provider", "base_url", "model", "api_format", "output_mode", "has_api_key", "revision"}


def fake_protect(data, *, decrypt=False):
    # 合成加密替代不调用系统凭证；对完整记录作可逆变换。
    return bytes(value ^ 0xA5 for value in data)


def api_input(**changes):
    data = {"provider": "api", "base_url": "https://models.example.test/v1/", "model": "test-model",
            "api_format": "chat_completions", "output_mode": "json_object", "api_key": CANARY}
    data.update(changes)
    return data


class ModelSettingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="mathpath-settings-test-")
        self.addCleanup(directory.cleanup)
        self.file = Path(directory.name) / "api_settings.dpapi"
        for patcher in (
            patch.object(settings, "SETTINGS_FILE", self.file),
            patch.object(settings, "protect_bytes", side_effect=fake_protect),
            patch.object(chatgpt_login, "load_session", side_effect=AssertionError("不可读取真实登录记录")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_defaults_are_public_and_do_not_create_storage(self):
        public = settings.get_public_settings()
        self.assertEqual(set(public), FIELDS)
        self.assertEqual(public["provider"], "chatgpt")
        self.assertEqual(public["base_url"], "https://api.openai.com/v1")
        self.assertEqual(public["model"], "")
        self.assertEqual(public["revision"], "default")
        self.assertFalse(public["has_api_key"])
        self.assertFalse(self.file.exists())

    def test_full_record_is_protected_and_key_never_returned(self):
        public = settings.save_settings(api_input())
        self.assertEqual(set(public), FIELDS)
        self.assertTrue(public["has_api_key"])
        self.assertEqual(public["base_url"], "https://models.example.test/v1")
        self.assertNotIn(CANARY, json.dumps(public))
        self.assertNotIn(CANARY.encode(), self.file.read_bytes())
        self.assertNotIn(b"test-model", self.file.read_bytes())
        private = json.loads(fake_protect(self.file.read_bytes(), decrypt=True))
        self.assertEqual(private["api_key"], CANARY)
        self.assertEqual(settings.get_public_settings(), public)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI 只在 Windows 可用")
    def test_actual_windows_dpapi_roundtrip_uses_only_temporary_synthetic_record(self):
        with patch.object(settings, "protect_bytes", side_effect=chatgpt_login.protect_bytes):
            saved = settings.save_settings(api_input())
            self.assertNotIn(CANARY.encode(), self.file.read_bytes())
            self.assertEqual(settings.get_public_settings(), saved)
            self.assertEqual(settings.resolve_generation_config().api_key, CANARY)

    def test_empty_null_and_omitted_key_preserve_saved_key(self):
        previous = settings.save_settings(api_input())
        for key_data in ({}, {"api_key": ""}, {"api_key": "   "}, {"api_key": None}):
            public = settings.save_settings({"provider": "api", "model": "changed-model", **key_data})
            self.assertTrue(public["has_api_key"])
            self.assertNotEqual(previous["revision"], public["revision"])
            self.assertEqual(settings.resolve_generation_config().api_key, CANARY)
            previous = public

    def test_clear_key_switches_to_chatgpt_without_touching_oauth(self):
        settings.save_settings(api_input())
        public = settings.save_settings(api_input(clear_api_key=True))
        self.assertEqual(public["provider"], "chatgpt")
        self.assertFalse(public["has_api_key"])
        private = json.loads(fake_protect(self.file.read_bytes(), decrypt=True))
        self.assertEqual(private["api_key"], "")
        chatgpt_login.load_session.assert_not_called()

    def test_choosing_chatgpt_preserves_api_key_for_later_explicit_choice(self):
        settings.save_settings(api_input())
        public = settings.save_settings({"provider": "chatgpt"})
        self.assertTrue(public["has_api_key"])
        self.assertEqual(settings.resolve_generation_config().provider, "chatgpt")
        self.assertEqual(settings.resolve_generation_config().api_key, "")
        self.assertEqual(settings.save_settings({"provider": "api"})["provider"], "api")

    def test_api_requires_key_and_model_without_changing_storage(self):
        for payload in (api_input(api_key=""), api_input(api_key=None), api_input(model="")):
            with self.subTest(payload_fields=set(payload)), self.assertRaises(settings.SettingsError) as caught:
                settings.save_settings(payload)
            self.assertNotIn(CANARY, str(caught.exception))
            self.assertFalse(self.file.exists())

    def test_invalid_values_produce_fixed_safe_errors_and_keep_old_config(self):
        settings.save_settings(api_input())
        before = self.file.read_bytes()
        bad = [api_input(provider=[]), api_input(api_format={}), api_input(output_mode=[]),
               api_input(model=CANARY * 30), api_input(api_key=CANARY * 200),
               api_input(api_key=CANARY + "\n"), api_input(model=42),
               api_input(clear_api_key="true"), {"secret": CANARY}]
        for payload in bad:
            with self.subTest(fields=set(payload)), self.assertRaises(settings.SettingsError) as caught:
                settings.save_settings(payload)
            self.assertNotIn(CANARY, str(caught.exception))
            self.assertEqual(self.file.read_bytes(), before)

    def test_base_url_rejects_unsafe_or_complete_endpoints(self):
        bad = ["http://models.example.test/v1", "https://user:" + CANARY + "@example.test/v1",
               "https://example.test/v1?key=" + CANARY, "https://example.test/v1#" + CANARY,
               "https://example.test/v1/chat/completions/", "https://example.test/v1/responses",
               "https://example.test/v1/%72esponses", "https://example.test:99999/v1",
               "https://example.test:bad/v1", "https://example.test:/v1", "https://example.test\n/v1",
               "https://example.test/v1/%0a", "https://example.test/v1/../responses",
               "http://localhost.example.test/v1", "http://127.0.0.2/v1", "ftp://example.test/v1",
               "https://example.test\\v1", "https:///v1", "https://example.test/v1?", "https://example.test/v1#"]
        for url in bad:
            with self.subTest(url=url), self.assertRaises(settings.SettingsError) as caught:
                settings.save_settings(api_input(base_url=url))
            self.assertNotIn(CANARY, str(caught.exception))

    def test_base_url_allows_https_and_exact_loopback_http(self):
        for url in ("https://api.example.test/custom/v1/", "http://localhost:8000/v1/",
                    "http://127.0.0.1:1234/v1/", "http://[::1]:8000/v1/"):
            with self.subTest(url=url):
                self.assertEqual(settings.save_settings(api_input(base_url=url))["base_url"], url.rstrip("/"))

    def test_snapshot_is_immutable_and_identity_has_no_secret(self):
        settings.save_settings(api_input())
        snapshot = settings.resolve_generation_config(override_model="ignored-oauth-model")
        self.assertEqual(snapshot.model, "test-model")
        self.assertNotIn(CANARY, repr(snapshot))
        identity = settings.config_identity(snapshot)
        self.assertEqual(set(identity), FIELDS - {"has_api_key"})
        self.assertNotIn(CANARY, json.dumps(identity))
        with self.assertRaises(FrozenInstanceError):
            snapshot.model = "mutated"
        settings.save_settings(api_input(model="later-model", api_key="synthetic-later-key"))
        self.assertEqual(snapshot.model, "test-model")
        self.assertEqual(snapshot.api_key, CANARY)
        self.assertNotEqual(identity, settings.config_identity(settings.resolve_generation_config()))

    def test_oauth_override_uses_actual_oauth_identity(self):
        default = settings.resolve_generation_config(default_model="default-oauth")
        override = settings.resolve_generation_config(default_model="default-oauth", override_model="explicit-oauth")
        self.assertEqual(default.model, "default-oauth")
        self.assertEqual(override.model, "explicit-oauth")
        self.assertEqual(override.base_url, chatgpt_login.RESOURCE)
        self.assertEqual(override.api_format, "responses")
        self.assertFalse(self.file.exists())

    def test_key_change_changes_revision_without_exposing_fingerprint(self):
        first = settings.save_settings(api_input())
        second = settings.save_settings(api_input(api_key="synthetic-replacement-key"))
        self.assertNotEqual(first["revision"], second["revision"])
        self.assertEqual(set(second), FIELDS)
        self.assertEqual(second["has_api_key"], True)

    def test_storage_and_decryption_failures_hide_exception_details(self):
        with patch.object(settings, "protect_bytes", side_effect=RuntimeError(CANARY)):
            with self.assertRaises(settings.SettingsError) as caught:
                settings.save_settings(api_input())
        self.assertNotIn(CANARY, str(caught.exception))
        self.file.write_bytes(CANARY.encode())
        with self.assertRaises(settings.SettingsError) as caught:
            settings.get_public_settings()
        self.assertNotIn(CANARY, str(caught.exception))

    def test_concurrent_saves_are_complete_and_preserve_saved_key(self):
        settings.save_settings(api_input())
        with ThreadPoolExecutor(max_workers=6) as pool:
            states = list(pool.map(lambda number: settings.save_settings({"model": "model-" + str(number)}), range(20)))
        self.assertEqual(len({state["revision"] for state in states}), 20)
        self.assertTrue(all(state["has_api_key"] for state in states))
        self.assertEqual(settings.resolve_generation_config().api_key, CANARY)


if __name__ == "__main__":
    unittest.main()
