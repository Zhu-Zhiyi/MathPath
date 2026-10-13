"""异步登录的离线检查；禁止实际网络、浏览器和凭证存储。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import chatgpt_connection as connection
import chatgpt_login as login


CANARY = "synthetic-secret-must-not-appear"
FIELDS = {"status", "message", "attempt"}


class ChatGPTConnectionTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = connection._ConnectionCoordinator()
        patches = [patch.object(connection, "_coordinator", self.coordinator),
                   patch.object(connection, "run_login")]
        # A missing mock fails before touching a real record, browser or socket.
        for name in ("load_session", "save_session", "protect_bytes", "host_id", "request_json"):
            patches.append(patch.object(login, name, side_effect=AssertionError("必须模拟登录资源")))
        patches.append(patch.object(login.webbrowser, "open", side_effect=AssertionError("必须模拟浏览器")))
        patches.append(patch.object(login.urllib.request, "build_opener",
                                    side_effect=AssertionError("必须模拟网络")))
        self.patches = patches
        for patcher in patches:
            result = patcher.start()
            self.addCleanup(patcher.stop)
            if patcher.attribute == "run_login":
                self.run_login = result
        self.release = threading.Event()
        self.addCleanup(self._stop_worker)

    def _stop_worker(self):
        self.release.set()
        worker = self.coordinator._worker
        if worker is not None and worker.ident is not None:
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive(), "模拟登录线程没有结束")

    def _finish_worker(self):
        worker = self.coordinator._worker
        self.assertIsNotNone(worker)
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive(), "模拟登录线程没有结束")
        return connection.get_connection_status()

    def test_fresh_status_does_not_claim_existing_account_is_signed_out(self):
        state = connection.get_connection_status()
        self.assertEqual(state, {"status": "idle", "message": "本次运行尚未发起登录。", "attempt": 0})
        self.run_login.assert_not_called()
        self.assertNotIn("未登录", state["message"])

    def test_async_pending_and_simultaneous_clicks_start_only_one_login(self):
        entered = threading.Event()

        def wait_for_browser():
            entered.set()
            self.assertTrue(self.release.wait(timeout=3))

        self.run_login.side_effect = wait_for_browser
        first = connection.start_connection()
        self.assertTrue(entered.wait(timeout=1))
        self.assertEqual(first["status"], "pending")
        self.assertEqual(first["attempt"], 1)
        self.assertTrue(self.coordinator._worker.daemon)
        with ThreadPoolExecutor(max_workers=8) as callers:
            repeated = list(callers.map(lambda _: connection.start_connection(), range(24)))
        self.assertTrue(all(result == first for result in repeated))
        self.assertEqual(connection.get_connection_status(), first)
        self.run_login.assert_called_once_with()
        self.release.set()
        self.assertEqual(self._finish_worker()["status"], "connected")

    def test_success_uses_safe_summary_and_discards_stdout(self):
        private_output = (
            "https://auth.example.test/authorize?code=" + CANARY + "\n"
            "email=synthetic@example.test token=" + CANARY + " client_id=" + CANARY + "\n"
            "账号可用模型：synthetic-private-model\n"
        )
        self.run_login.side_effect = lambda: print(private_output)
        visible = io.StringIO()
        with redirect_stdout(visible):
            first = connection.start_connection()
            completed = self._finish_worker()
        self.assertEqual(first["status"], "pending")
        self.assertEqual(completed, {"status": "connected", "message": connection._CONNECTED_MESSAGE,
                                     "attempt": 1})
        self.assertEqual(visible.getvalue(), "")
        self.assertEqual(set(completed), FIELDS)
        for private in (CANARY, "synthetic@example.test", "client_id", "synthetic-private-model", "authorize"):
            self.assertNotIn(private, json.dumps(completed))

    def test_login_error_returns_existing_safe_diagnosis(self):
        self.run_login.side_effect = login.OAuthTransportError("tls")
        connection.start_connection()
        completed = self._finish_worker()
        self.assertEqual(completed["status"], "error")
        self.assertEqual(completed["message"], login.TRANSPORT_MESSAGES["tls"])
        self.assertEqual(completed["attempt"], 1)

    def test_empty_login_error_returns_safe_retry_message(self):
        self.run_login.side_effect = login.LoginError()
        connection.start_connection()
        self.assertEqual(self._finish_worker()["message"], connection._ERROR_MESSAGE)

    def test_unknown_error_never_exposes_exception_text(self):
        self.run_login.side_effect = RuntimeError("https://example.test/" + CANARY)
        connection.start_connection()
        completed = self._finish_worker()
        self.assertEqual(completed["status"], "error")
        self.assertEqual(completed["message"], connection._ERROR_MESSAGE)
        self.assertNotIn(CANARY, json.dumps(completed))
        self.assertNotIn("RuntimeError", json.dumps(completed))

    def test_completed_login_without_model_permission_is_still_connected(self):
        self.run_login.side_effect = lambda: print("订阅权限：未启用。" + CANARY)
        connection.start_connection()
        completed = self._finish_worker()
        self.assertEqual(completed["status"], "connected")
        self.assertEqual(completed["message"], "登录已完成，当前未启用模型调用权限。")
        self.assertNotIn(CANARY, completed["message"])

    def test_printed_success_before_login_error_does_not_report_connected(self):
        def fail_after_save():
            print("登录验证成功。" + CANARY)
            raise login.LoginError("登录已保存，但可用模型列表格式不符合预期。")

        self.run_login.side_effect = fail_after_save
        connection.start_connection()
        completed = self._finish_worker()
        self.assertEqual(completed["status"], "error")
        self.assertEqual(completed["message"], "登录已保存，但可用模型列表格式不符合预期。")
        self.assertNotIn(CANARY, json.dumps(completed))

    def test_returned_state_cannot_mutate_coordinator(self):
        state = connection.get_connection_status()
        state.update(status="connected", message=CANARY, attempt=99)
        self.assertEqual(connection.get_connection_status()["status"], "idle")
        self.assertEqual(connection.get_connection_status()["attempt"], 0)
        first = connection.start_connection()
        first["message"] = CANARY
        completed = self._finish_worker()
        self.assertNotIn(CANARY, json.dumps(completed))

    def test_retry_after_success_or_error_starts_next_attempt(self):
        for first_failure in (None, login.LoginError("授权未完成或已取消。")):
            with self.subTest(first_failure=first_failure is not None):
                self.run_login.side_effect = first_failure
                first = connection.start_connection()
                completed = self._finish_worker()
                self.assertEqual(completed["attempt"], first["attempt"])
                self.assertEqual(completed["status"], "error" if first_failure else "connected")
                self.run_login.side_effect = None
                second = connection.start_connection()
                self.assertEqual(second["status"], "pending")
                self.assertEqual(second["attempt"], first["attempt"] + 1)
                self.assertEqual(self._finish_worker()["status"], "connected")
        self.assertEqual(self.run_login.call_count, 4)

    def test_stale_or_repeated_completion_cannot_replace_current_state(self):
        entered = threading.Event()

        def wait_for_browser():
            entered.set()
            self.assertTrue(self.release.wait(timeout=3))

        self.run_login.side_effect = wait_for_browser
        pending = connection.start_connection()
        self.assertTrue(entered.wait(timeout=1))
        self.coordinator._finish(pending["attempt"] - 1, "error", "过期的尝试")
        self.assertEqual(connection.get_connection_status(), pending)
        self.release.set()
        completed = self._finish_worker()
        self.coordinator._finish(pending["attempt"], "error", "重复的结果")
        self.assertEqual(connection.get_connection_status(), completed)

    def test_thread_start_error_returns_safe_error_and_allows_retry(self):
        with patch.object(connection.threading.Thread, "start", side_effect=RuntimeError(CANARY)):
            failed = connection.start_connection()
        self.assertEqual(failed, {"status": "error", "message": connection._ERROR_MESSAGE, "attempt": 1})
        self.run_login.assert_not_called()
        second = connection.start_connection()
        self.assertEqual(second["attempt"], 2)
        self.assertEqual(self._finish_worker()["status"], "connected")


if __name__ == "__main__":
    unittest.main()
