"""Desktop requests must originate from their own loopback page, never a foreign site."""
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import chatgpt_login
import main


class DesktopBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.previous = main.app.state.desktop_local_only
        main.app.state.desktop_local_only = True
        self.client = TestClient(main.app, base_url="http://127.0.0.1:8123")

    def tearDown(self):
        self.client.close()
        main.app.state.desktop_local_only = self.previous

    def test_local_health_and_same_origin_plan_are_accepted(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        graph = self.client.get("/example").json()
        response = self.client.post("/plan", headers={"Origin": "http://127.0.0.1:8123"},
                                    json={"graph": graph, "known_ids": []})
        self.assertEqual(response.status_code, 200)

    def test_foreign_host_cannot_reach_model(self):
        with patch.object(main, "build_graph") as model:
            for host in ["untrusted.example:8123", "127.0.0.1.evil.example:8123", "127.0.0.1:8124"]:
                with self.subTest(host=host):
                    result = self.client.post("/analyze", headers={"Host": host}, json={"text": "goal"})
                    self.assertEqual(result.status_code, 403)
            model.assert_not_called()

    def test_foreign_null_or_duplicate_origin_cannot_reach_model(self):
        with patch.object(main, "build_graph") as model:
            for origin in ["https://untrusted.example", "null", "http://127.0.0.1:8124"]:
                with self.subTest(origin=origin):
                    result = self.client.post("/analyze", headers={"Origin": origin}, json={"text": "goal"})
                    self.assertEqual(result.status_code, 403)
            result = self.client.post("/analyze", headers=[("Origin", "http://127.0.0.1:8123"),
                ("Origin", "http://127.0.0.1:8123")], json={"text": "goal"})
            self.assertEqual(result.status_code, 403)
            model.assert_not_called()

    def test_duplicate_host_is_rejected(self):
        result = self.client.get("/health", headers=[("Host", "127.0.0.1:8123"), ("Host", "untrusted.example")])
        self.assertEqual(result.status_code, 403)

    def test_source_development_interface_remains_usable(self):
        main.app.state.desktop_local_only = False
        with TestClient(main.app) as development:
            self.assertEqual(development.get("/health").status_code, 200)


class DesktopLoginHintTests(unittest.TestCase):
    def test_packaged_login_errors_point_to_menu(self):
        with patch.object(sys, "frozen", True, create=True):
            result = str(chatgpt_login.LoginError("尚未登录 ChatGPT，请运行 chatgpt_login.py 完成登录。"))
        self.assertIn("MathPath → 连接 ChatGPT", result)
        self.assertNotIn("chatgpt_login.py", result)

    def test_source_hint_and_safe_transport_diagnosis_are_preserved(self):
        message = "请运行 chatgpt_login.py 重新登录。"
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(str(chatgpt_login.LoginError(message)), message)
        with patch.object(sys, "frozen", True, create=True):
            self.assertEqual(str(chatgpt_login.OAuthTransportError("tls")), chatgpt_login.TRANSPORT_MESSAGES["tls"])


if __name__ == "__main__":
    unittest.main()
