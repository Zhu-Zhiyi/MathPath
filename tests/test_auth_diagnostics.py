"""OAuth 诊断的离线检查；所有网络和凭证存储均由模拟替代。"""

from contextlib import nullcontext
import copy
import io
import json
from pathlib import Path
import ssl
import sys
import unittest
from unittest.mock import MagicMock, patch
import urllib.error


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import chatgpt_login as login


CANARY = "synthetic-secret-must-not-appear"
URL = "https://example.test/" + CANARY


def expired_session():
    return {
        "issuer": login.ISSUER,
        "subject": "synthetic-subject",
        "client_id": "synthetic-client",
        "access_token": "synthetic-access-token",
        "refresh_token": "synthetic-refresh-token",
        "token_type": "Bearer",
        "expires_at": 0,
        "scopes": ["resource.invoke", "chatgpt.tokens.use.direct", "offline_access"],
    }


class AuthDiagnosticTests(unittest.TestCase):
    def setUp(self):
        # A missing mock must fail before touching actual credentials or sockets.
        for name in ("load_session", "save_session", "_session_transaction"):
            guard = patch.object(login, name, side_effect=AssertionError("必须模拟凭证存储"))
            guard.start()
            self.addCleanup(guard.stop)
        guard = patch.object(login.urllib.request, "build_opener", side_effect=AssertionError("必须模拟网络"))
        guard.start()
        self.addCleanup(guard.stop)

    def test_transport_categories_do_not_echo_exception_or_request(self):
        cases = [
            (TimeoutError(CANARY), "timeout"),
            (urllib.error.URLError(TimeoutError(CANARY)), "timeout"),
            (ssl.SSLEOFError(1, CANARY), "tls"),
            (urllib.error.URLError(ssl.SSLError(1, CANARY)), "tls"),
            (ConnectionResetError(CANARY), "connection"),
            (urllib.error.URLError(CANARY), "connection"),
        ]
        for error, expected in cases:
            with self.subTest(kind=type(error).__name__, category=expected):
                opener = MagicMock()
                opener.open.side_effect = error
                with patch.object(login.urllib.request, "build_opener", return_value=opener):
                    with self.assertRaises(login.OAuthTransportError) as caught:
                        login.request_json(URL, form={"refresh_token": CANARY}, bearer=CANARY)
                self.assertEqual(caught.exception.category, expected)
                self.assertEqual(str(caught.exception), login.TRANSPORT_MESSAGES[expected])
                self.assertNotIn(CANARY, str(caught.exception))

    def test_http_status_and_allowlisted_code_survive_safe_parsing(self):
        for body, expected in (
            ({"error": "temporarily_unavailable", "detail": CANARY}, "temporarily_unavailable"),
            ({"error": {"code": "server_error", "message": CANARY}}, "server_error"),
            ({"error": CANARY}, ""),
        ):
            with self.subTest(code=expected):
                failure = urllib.error.HTTPError(URL, 503, CANARY, {},
                    io.BytesIO(json.dumps(body).encode("utf-8")))
                opener = MagicMock()
                opener.open.side_effect = failure
                with patch.object(login.urllib.request, "build_opener", return_value=opener):
                    with self.assertRaises(login.OAuthRequestError) as caught:
                        login.request_json(URL)
                self.assertEqual(caught.exception.status_code, 503)
                self.assertEqual(caught.exception.error_code, expected)
                self.assertNotIn(CANARY, str(caught.exception))

    def test_refresh_preserves_credentials_and_reports_transport_category(self):
        for category in ("timeout", "tls", "connection"):
            with self.subTest(category=category):
                record = expired_session()
                before = copy.deepcopy(record)
                with patch.object(login, "_session_transaction", return_value=nullcontext()), \
                        patch.object(login, "load_session", return_value=record), \
                        patch.object(login, "save_session") as save, \
                        patch.object(login, "load_discovery", return_value={"token_endpoint": URL}), \
                        patch.object(login, "request_json", side_effect=login.OAuthTransportError(category)):
                    with self.assertRaises(login.LoginError) as caught:
                        login.get_usable_session()
                self.assertIn("原登录记录已保留", str(caught.exception))
                self.assertIn(login.TRANSPORT_MESSAGES[category], str(caught.exception))
                self.assertEqual(record, before)
                save.assert_not_called()

    def test_temporary_refresh_http_error_keeps_status_code_and_credentials(self):
        record = expired_session()
        before = copy.deepcopy(record)
        with patch.object(login, "_session_transaction", return_value=nullcontext()), \
                patch.object(login, "load_session", return_value=record), \
                patch.object(login, "save_session") as save, \
                patch.object(login, "load_discovery", return_value={"token_endpoint": URL}), \
                patch.object(login, "request_json", side_effect=login.OAuthRequestError(503, "server_error")):
            with self.assertRaises(login.LoginError) as caught:
                login.get_usable_session()
        self.assertIn("HTTP 503", str(caught.exception))
        self.assertIn("server_error", str(caught.exception))
        self.assertIn("原登录记录已保留", str(caught.exception))
        self.assertEqual(record, before)
        save.assert_not_called()

    def test_unknown_login_exception_still_hides_message(self):
        record = expired_session()
        with patch.object(login, "_session_transaction", return_value=nullcontext()), \
                patch.object(login, "load_session", return_value=record), \
                patch.object(login, "save_session") as save, \
                patch.object(login, "load_discovery", return_value={"token_endpoint": URL}), \
                patch.object(login, "request_json", side_effect=login.LoginError(CANARY)):
            with self.assertRaises(login.LoginError) as caught:
                login.get_usable_session()
        self.assertNotIn(CANARY, str(caught.exception))
        save.assert_not_called()

    def test_discovery_transport_error_reaches_caller_without_storage_change(self):
        record = expired_session()
        with patch.object(login, "_session_transaction", return_value=nullcontext()), \
                patch.object(login, "load_session", return_value=record), \
                patch.object(login, "save_session") as save, \
                patch.object(login, "load_discovery", side_effect=login.OAuthTransportError("tls")), \
                patch.object(login, "request_json") as request:
            with self.assertRaises(login.OAuthTransportError) as caught:
                login.get_usable_session()
        self.assertEqual(caught.exception.category, "tls")
        save.assert_not_called()
        request.assert_not_called()

    def test_error_constructors_reject_untrusted_diagnostic_fields(self):
        failure = login.OAuthRequestError(CANARY, CANARY)
        self.assertNotIn(CANARY, str(failure))
        self.assertEqual(failure.error_code, "")
        transport = login.OAuthTransportError(CANARY)
        self.assertEqual(transport.category, "connection")
        self.assertNotIn(CANARY, str(transport))


if __name__ == "__main__":
    unittest.main()
