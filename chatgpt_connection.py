"""网页和原生菜单共用的 ChatGPT 登录进度；不读取已有登录记录。"""

from contextlib import redirect_stdout
import io
import threading

from chatgpt_login import LoginError, run_login


__all__ = ["start_connection", "get_connection_status"]

_IDLE_MESSAGE = "本次运行尚未发起登录。"
_PENDING_MESSAGE = "正在连接 ChatGPT，请在打开的浏览器中完成登录。"
_CONNECTED_MESSAGE = "ChatGPT 已连接，可以返回生成学习内容。"
_NO_MODEL_PERMISSION_MESSAGE = "登录已完成，当前未启用模型调用权限。"
_ERROR_MESSAGE = "连接 ChatGPT 未完成，请稍后重试。"


class _ConnectionCoordinator:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = {"status": "idle", "message": _IDLE_MESSAGE, "attempt": 0}
        self._worker = None

    def status(self):
        with self._lock:
            return dict(self._state)

    def start(self):
        with self._lock:
            if self._state["status"] == "pending":
                return dict(self._state)
            attempt = self._state["attempt"] + 1
            self._state = {"status": "pending", "message": _PENDING_MESSAGE, "attempt": attempt}
            try:
                worker = threading.Thread(target=self._connect, args=(attempt,),
                                          name="mathpath-chatgpt-login", daemon=True)
                self._worker = worker
                worker.start()
            except Exception:
                self._state = {"status": "error", "message": _ERROR_MESSAGE, "attempt": attempt}
                self._worker = None
            # The lock makes this first response pending even if login finishes immediately.
            return dict(self._state)

    def _connect(self, attempt):
        status, message = "connected", _CONNECTED_MESSAGE
        try:
            # run_login may print an authorization URL or account/model details. Keep
            # them only in this temporary memory buffer, never in logs or public state.
            with io.StringIO() as output, redirect_stdout(output):
                run_login()
                if "订阅权限：未启用" in output.getvalue():
                    message = _NO_MODEL_PERMISSION_MESSAGE
        except LoginError as exc:
            status, message = "error", str(exc) or _ERROR_MESSAGE
        except Exception:
            status, message = "error", _ERROR_MESSAGE
        self._finish(attempt, status, message)

    def _finish(self, attempt, status, message):
        with self._lock:
            # A result belongs only to its own still-pending attempt.
            if self._state["attempt"] == attempt and self._state["status"] == "pending":
                self._state = {"status": status, "message": message, "attempt": attempt}


# Both HTTP routes and the native menu must import these functions, sharing this
# process-wide coordinator instead of creating separate login threads or locks.
_coordinator = _ConnectionCoordinator()


def start_connection():
    """开始一次后台登录；已有登录仍在等待时返回同一份安全进度。"""
    return _coordinator.start()


def get_connection_status():
    """仅返回本次进程的登录进度；不读取、验证或透露已有凭证。"""
    return _coordinator.status()
