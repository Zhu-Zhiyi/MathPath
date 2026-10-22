"""MathPath Windows desktop entry point, including offline release checks.

The executable contains application resources, but never account credentials.
Authentication and the browser profile live under the current user's AppData.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
from uuid import uuid4

APP_NAME = "MathPath"
APP_VERSION = "0.5.1"
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


class DesktopError(Exception):
    """A deliberately safe, user-facing startup error."""


class OfflineBoundary:
    """Release tests may use temporary data but cannot authenticate or call a model."""

    def __init__(self):
        self.counts = {"model_requests": 0, "chatgpt_login_attempts": 0,
                       "credential_reads": 0, "external_auth_requests": 0}
        self.originals = []

    def install(self) -> None:
        import chatgpt_connection
        import chatgpt_login
        import llm_client

        def block(counter):
            def forbidden(*args, **kwargs):
                self.counts[counter] += 1
                raise DesktopError("offline-boundary-was-crossed")
            return forbidden

        for module, name, counter in [
            (llm_client, "OpenAI", "model_requests"),
            (llm_client, "get_usable_session", "credential_reads"),
            (chatgpt_login, "get_usable_session", "credential_reads"),
            (chatgpt_login, "load_session", "credential_reads"),
            (chatgpt_login, "request_json", "external_auth_requests"),
            (chatgpt_login, "run_login", "chatgpt_login_attempts"),
            (chatgpt_connection, "run_login", "chatgpt_login_attempts"),
        ]:
            self.originals.append((module, name, getattr(module, name)))
            setattr(module, name, block(counter))

    def restore(self) -> None:
        for module, name, original in reversed(self.originals):
            setattr(module, name, original)
        self.originals.clear()


def app_data_dir() -> Path:
    override = os.environ.get("MATHPATH_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / APP_NAME


def configure_data_dir(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    os.environ["MATHPATH_DATA_DIR"] = str(directory)
    os.environ["MATHPATH_DESKTOP"] = "1"
    # No requests, prompts, callback parameters or tokens are logged to disk.
    logging.disable(logging.CRITICAL)


def show_error(message: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    elif sys.stderr is not None:
        print(message, file=sys.stderr)


class SingleInstance:
    """An OS mutex prevents concurrent writes to one WebView2 profile."""

    def __init__(self, directory: Path):
        self.handle = None
        self.owns = False
        if os.name != "nt":
            return
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        digest = hashlib.sha256(str(directory).casefold().encode()).hexdigest()[:24]
        self.kernel = kernel
        self.handle = kernel.CreateMutexW(None, True, "Local\\MathPath-" + digest)
        if not self.handle:
            raise DesktopError("无法取得应用锁。请重新启动 MathPath。")
        self.owns = ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        if self.owns:
            return True
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user.FindWindowW.restype = wintypes.HWND
        user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user.SetForegroundWindow.argtypes = [wintypes.HWND]
        hwnd = user.FindWindowW(None, APP_NAME)
        if hwnd:
            user.ShowWindow(hwnd, 9)  # SW_RESTORE
            user.SetForegroundWindow(hwnd)
        return False

    def close(self) -> None:
        if self.handle:
            if self.owns:
                self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def reserve_socket(directory: Path, persistent: bool = True) -> socket.socket:
    settings_path = directory / "desktop.json"
    preferred_port = 0
    if persistent:
        try:
            port = json.loads(settings_path.read_text(encoding="utf-8")).get("port")
            if type(port) is int and 1024 <= port <= 65535:
                preferred_port = port
        except (OSError, ValueError, AttributeError):
            pass
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt":
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        try:
            listener.bind(("127.0.0.1", preferred_port))
        except OSError:
            if persistent and preferred_port:
                raise DesktopError("MathPath 的本机端口被其他程序占用。请关闭占用程序后重新打开 MathPath；学习进度仍会保留。") from None
            raise
        listener.listen(128)
        if persistent:
            payload = json.dumps({"port": listener.getsockname()[1]})
            temporary = directory / "desktop.json.tmp"
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(settings_path)
        return listener
    except BaseException:
        listener.close()
        raise


class LocalServer:
    def __init__(self, directory: Path, persistent: bool = True):
        import uvicorn
        from main import app

        self.socket = reserve_socket(directory, persistent)
        self.port = self.socket.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}/"
        self.failure = None
        self.server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=self.port, log_config=None,
            access_log=False, loop="asyncio", http="h11", ws="none",
            lifespan="on", timeout_graceful_shutdown=2,
        ))
        self.thread = threading.Thread(target=self._run, name="MathPath-server", daemon=True)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _run(self) -> None:
        try:
            self.server.run(sockets=[self.socket])
        except BaseException as exc:
            self.failure = type(exc).__name__

    def start(self) -> None:
        self.thread.start()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.failure or not self.thread.is_alive():
                raise DesktopError("MathPath 本机服务未能启动。请重新打开应用。")
            if self.server.started:
                try:
                    if self.request("health") == {"status": "ok"}:
                        return
                except (OSError, ValueError):
                    pass
            time.sleep(.1)
        raise DesktopError("MathPath 本机服务启动超时。请重新打开应用。")

    def request(self, path: str, body=None, *, method: str | None = None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.url + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        with self.opener.open(request, timeout=5) as response:
            if "application/json" in response.headers.get("Content-Type", ""):
                return json.load(response)
            return response.read()

    def stop(self) -> bool:
        self.server.should_exit = True
        if self.thread.ident is not None:
            self.thread.join(4)
            if self.thread.is_alive():
                self.server.force_exit = True
                self.thread.join(1)
        self.socket.close()
        return not self.thread.is_alive()


def runtime_version() -> str:
    """Ask Microsoft's bundled loader without invoking authentication."""
    import webview
    loader_path = Path(webview.__file__).parent / "lib" / "runtimes" / "win-x64" / "native" / "WebView2Loader.dll"
    loader = ctypes.WinDLL(str(loader_path))
    probe = loader.GetAvailableCoreWebView2BrowserVersionString
    probe.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    probe.restype = ctypes.c_long
    version = ctypes.c_void_p()
    result = probe(None, ctypes.byref(version))
    if result < 0 or not version.value:
        raise DesktopError("MathPath 需要 Microsoft Edge WebView2 Runtime。请安装后重新打开。\nhttps://developer.microsoft.com/microsoft-edge/webview2/")
    try:
        return ctypes.wstring_at(version)
    finally:
        ctypes.windll.ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.ole32.CoTaskMemFree(version)


def self_test(server: LocalServer) -> dict:
    html = server.request("")
    assert b"<title>MathPath" in html, "html-title"
    assert b"goal-form" in html, "html-ui"
    assert len(server.request("static/app.js")) > 1000, "javascript-resource"
    assert len(server.request("static/style.css")) > 1000, "css-resource"
    assert len(server.request("static/vendor/katex/katex.min.js")) > 100000, "offline-katex-script"
    assert server.request("static/vendor/katex/fonts/KaTeX_Main-Regular.woff2")[:4] == b"wOF2", "offline-katex-font"
    graph = server.request("example")
    assert len(graph["nodes"]) >= 2, "curated-graph"
    status = server.request("plan", {"graph": graph, "known_ids": []})
    assert isinstance(status, dict), "offline-planner"
    lessons = {}
    for node in graph["nodes"]:
        lesson = server.request("lesson", {"graph": graph, "node_id": node["id"]})
        assert lesson.get("definition") and lesson.get("exercise") and lesson.get("source") == "curated_example", "curated-lesson"
        assert len(lesson.get("followup_exercises", [])) >= 2, "curated-followup-exercises"
        assert lesson.get("illustration"), "curated-illustration"
        lessons[node["id"]] = lesson
    assert graph.get("study_plan", {}).get("math_context"), "shared-mathematical-context"
    first_id = graph["nodes"][0]["id"]
    tasks = server.request("study/tasks", {"graph": graph, "node_id": first_id, "kind": "lesson", "lesson": lessons[first_id]})
    exercise = next(task for task in tasks["tasks"] if task["format"] == "choice")
    feedback = server.request("study/feedback", {"graph": graph, "node_id": first_id, "task_id": exercise["id"],
                              "answer": str(exercise["correct_index"]), "hint_level": 0, "lesson": lessons[first_id], "use_model": False})
    assert feedback["source"] == "local_check" and feedback["outcome"] == "correct", "offline-choice-feedback"
    open_task = next(task for task in tasks["tasks"] if task["format"] == "open")
    comparison = server.request("study/feedback", {"graph": graph, "node_id": first_id, "task_id": open_task["id"],
                                "answer": "这是用于离线自检的合成作答。", "hint_level": 1, "lesson": lessons[first_id], "use_model": False})
    assert comparison["source"] == "local_reference" and comparison["outcome"] == "needs_review" and comparison["review_required"], "open-reference-not-auto-graded"
    chat_turns = []
    for question in ("请解释本卡的链与系数。", "沿用刚才的约定，说明为什么需要保留方向。"):
        chat_answer = server.request("study/chat", {"graph": graph, "node_id": first_id,
            "question": question, "lesson": lessons[first_id], "turns": chat_turns, "use_model": False})
        assert set(chat_answer) == {"response", "source", "review_required", "answer_status", "problem_id", "problem_save_failed"}, "offline-chat-response-fields"
        assert chat_answer["response"].strip() and chat_answer["source"] == "local_reference" and chat_answer["review_required"] is True, "offline-chat-is-reference"
        assert chat_answer["answer_status"] == "uncertain" and chat_answer["problem_id"] and chat_answer["problem_save_failed"] is False, "offline-chat-queued-as-unresolved"
        chat_turns.append({"id": str(uuid4()), "node_id": first_id, "question": question,
            **{key: chat_answer[key] for key in ("response", "source", "review_required", "answer_status")},
            "created_at": datetime.now(timezone.utc).isoformat()})
    queued = server.request("library/problems")
    assert len(queued) == 2 and {item["question"] for item in queued} == {turn["question"] for turn in chat_turns}, "two-local-questions-queued"
    assert all(item["status"] == "open" and item["reason"] == "uncertain" for item in queued), "queued-question-status"
    broad_goal = server.request("study/scope", {"text": "我想学数学", "mode": "intuition"})
    assert broad_goal["needs_selection"] is True and 3 <= len(broad_goal["options"]) <= 5, "broad-goal-direction-options"
    assert all(item["goal"].strip() and item["title"].strip() for item in broad_goal["options"]), "specific-direction-goals"
    specific_goal = server.request("study/scope", {"text": "理解同调群为什么要将循环群对边界群取商", "mode": "proof"})
    assert specific_goal["needs_selection"] is False and specific_goal["options"] == [], "specific-goal-not-interrupted"
    references = server.request("study/references", {"graph": graph, "node_id": graph["target_id"]})
    assert any(book["title"] == "Algebraic Topology" and book["author"] == "Allen Hatcher"
               and book["url"] == "https://pi.math.cornell.edu/~hatcher/AT/ATpage.html"
               and "2.1" in book["section"] for book in references["books"]), "verified-hatcher-reference"
    project = server.request("library/projects", {"title": "离线自检项目"})
    histories = [server.request("library/histories", {"title": f"离线历史 {index}", "goal": "合成测试学习目标",
        "project_id": project["id"], "graph": graph,
        "state": {"lessons": {first_id: lessons[first_id]}, "notes": {first_id: "仅测试数据"}, "graph_source": "example"}})
        for index in range(2)]
    saved = server.request("library/histories/" + histories[0]["id"], {
        "expected_revision": histories[0]["revision"], "state": {"notes": {first_id: "重启后应恢复的合成笔记"},
            "chat_turns": chat_turns, "graph_source": "example"}}, method="PATCH")
    restored = server.request("library/histories/" + saved["id"])
    assert restored == saved and restored["revision"] == 2, "sqlite-history-save-restore"
    assert restored["state"]["chat_turns"] == chat_turns, "chat-history-roundtrip"
    linked_question = server.request("library/problems", {"history_id": saved["id"], "node_id": first_id,
        "question": "手动保留的自检问题：如何检查这个方向？", "response": "合成参考内容。", "reason": "user_marked"})
    assert linked_question["goal"] == saved["goal"] and linked_question["node_label"] == graph["nodes"][0]["label"], "unresolved-question-context-snapshot"
    resolved = server.request("library/problems/" + linked_question["id"], {"status": "resolved"}, method="PATCH")
    assert resolved["status"] == "resolved" and any(item["id"] == linked_question["id"] for item in server.request("library/problems?status=resolved")), "problem-resolution-explicit"
    reopened = server.request("library/problems/" + linked_question["id"], {"status": "open"}, method="PATCH")
    assert reopened["status"] == "open" and reopened["question"] == linked_question["question"], "problem-reopen-preserves-question"
    assert server.request("library/histories/" + histories[1]["id"])["state"]["chat_turns"] == [], "chat-histories-isolated"
    metadata = server.request("library/histories")
    assert len(metadata) == 2 and all("graph" not in item and "state" not in item for item in metadata), "metadata-only-history-list"
    server.request("library/histories/move", {"ids": [item["id"] for item in histories], "project_id": None})
    server.request("library/histories/move", {"ids": [item["id"] for item in histories], "project_id": project["id"]})
    server.request("library/projects/delete", {"ids": [project["id"]]})
    kept = [server.request("library/histories/" + item["id"]) for item in histories]
    assert all(item["project_id"] is None for item in kept), "project-delete-retains-history"
    assert kept[0]["state"]["notes"][first_id] == "重启后应恢复的合成笔记", "project-delete-retains-notes"
    assert kept[0]["state"]["chat_turns"] == chat_turns, "project-delete-retains-chat"
    server.request("library/histories/delete", {"ids": [item["id"] for item in histories]})
    assert server.request("library/histories") == [] and server.request("library/projects") == [], "batch-history-delete"
    detached = server.request("library/problems/" + linked_question["id"])
    assert detached["history_id"] is None and all(detached[key] == linked_question[key] for key in
        ("goal", "node_id", "node_label", "question", "response", "reason", "created_at")), "unresolved-question-retained-after-history-delete"
    example_checks = _check_multiple_examples(server, graph, lessons)
    backup_checks = _check_full_backup(server, graph, lessons[first_id], exercise, chat_turns)
    settings = server.request("settings/model")
    public_fields = {"provider", "base_url", "model", "api_format", "output_mode", "has_api_key", "revision"}
    assert set(settings) == public_fields and settings["has_api_key"] is False, "temporary-default-settings"
    assert (settings["provider"], settings["base_url"], settings["model"],
            settings["api_format"], settings["output_mode"]) == (
        "api", "https://models.sjtu.edu.cn/api/v1", "deepseek-reasoner",
        "chat_completions", "json_object"), "fresh-deepseek-default-configuration"
    # Missing-key handling must finish before an SDK client, OAuth session or
    # environment credential can be consulted. The offline guard stays active.
    from model_settings import SETTINGS_FILE, SettingsError, resolve_generation_config
    assert not SETTINGS_FILE.exists(), "fresh-default-config-is-not-written"
    try:
        resolve_generation_config()
    except SettingsError as error:
        assert "API 密钥" in str(error), "missing-deepseek-key-explained"
    else:
        raise AssertionError("default-deepseek-was-usable-without-explicit-key")
    assert not SETTINGS_FILE.exists(), "missing-key-does-not-write-config"
    # The entry point has already isolated all data in a fresh test directory.
    # Save only this synthetic value; never call the connection-test endpoint.
    synthetic_key = "synthetic-desktop-test-only-key"
    saved_settings = server.request("settings/model", {
        "provider": "api", "base_url": "https://example.invalid/v1", "model": "offline-test-model",
        "api_format": "chat_completions", "output_mode": "json_object", "api_key": synthetic_key,
    })
    assert set(saved_settings) == public_fields and saved_settings["has_api_key"] is True, "synthetic-api-settings"
    assert synthetic_key not in json.dumps(saved_settings), "saved-key-not-echoed"
    settings = server.request("settings/model")
    assert set(settings) == public_fields and settings["has_api_key"] is True, "saved-settings-metadata"
    assert synthetic_key not in json.dumps(settings), "settings-key-not-echoed"
    connection = server.request("settings/chatgpt/status")
    assert set(connection) == {"status", "message", "attempt"}, "safe-chatgpt-status"
    assert connection["status"] == "idle" and connection["attempt"] == 0, "fresh-runtime-no-login-attempt"
    assert isinstance(connection["message"], str) and connection["message"], "safe-chatgpt-status-message"
    with tempfile.TemporaryDirectory(prefix="mathpath-contract-check-") as temporary:
        directory = Path(temporary)
        first = reserve_socket(directory)
        port = first.getsockname()[1]
        first.close()
        second = reserve_socket(directory)
        assert second.getsockname()[1] == port, "persistent-port"
        original_settings = (directory / "desktop.json").read_bytes()
        try:
            try:
                unexpected = reserve_socket(directory)
            except DesktopError:
                pass
            else:
                unexpected.close()
                raise AssertionError("occupied-port-was-replaced")
            assert (directory / "desktop.json").read_bytes() == original_settings, "port-config-preserved"
        finally:
            second.close()
        first_instance = SingleInstance(directory)
        second_instance = SingleInstance(directory)
        try:
            assert first_instance.owns and not second_instance.owns, "single-instance-mutex"
        finally:
            second_instance.close()
            first_instance.close()
    return {"status": "ok", "version": APP_VERSION, "packaged": bool(getattr(sys, "frozen", False)),
            "loopback": True, "resources": True, "example_nodes": len(graph["nodes"]),
            "curated_lesson": True, "model_requests": 0, "persistent_port": True,
            "occupied_port_rejected": True, "single_instance": True,
            "enriched_curated_lessons": len(graph["nodes"]), "api_settings_synthetic_config": True,
            "default_deepseek_configuration": True, "deepseek_requires_explicit_api_key": True,
            "saved_api_key_not_echoed": True, "configuration_directory": "temporary",
            "api_connection_tests": 0, "chatgpt_status_readonly_idle": True,
            "chatgpt_login_attempts": 0, "chatgpt_authorization_started": False,
            "sqlite_history_save_restore": True, "project_delete_retains_history": True,
            "batch_history_move_delete": True, "metadata_only_history_list": True,
            "offline_katex_resources": True, "shared_mathematical_context": True,
            "offline_choice_feedback": True, "open_reference_not_auto_graded": True,
            "offline_chat_two_turns": True, "chat_history_roundtrip": True,
            "chat_histories_isolated": True, "project_delete_retains_chat": True,
            "unresolved_problem_history": True, "unresolved_question_retained_after_history_delete": True,
            "goal_scope_preflight": True, "verified_book_catalog": True, **example_checks, **backup_checks}


def _check_multiple_examples(server: LocalServer, homology_graph: dict, homology_lessons: dict) -> dict:
    """Exercise every bundled card and task through actual offline service routes."""
    catalog = server.request("examples")
    assert {item["id"] for item in catalog} == {"homology", "rank_nullity", "epsilon_delta"}, "three-offline-examples"
    assert all(set(item) == {"id", "title", "description", "goal"} for item in catalog), "safe-example-catalog"
    task_ids, card_count = set(), 0
    for item in catalog:
        graph = homology_graph if item["id"] == "homology" else server.request("example?example_id=" + item["id"])
        context = graph["study_plan"]["math_context"]
        assert context.strip() and graph["study_plan"]["criteria"], "example-context-and-criteria"
        global_tasks = server.request("study/tasks", {"graph": graph})["tasks"]
        for task in global_tasks:
            assert task["id"] not in task_ids and task["source"] == "curated_example", "unique-curated-global-task"
            task_ids.add(task["id"])
        for node in graph["nodes"]:
            lesson = homology_lessons[node["id"]] if item["id"] == "homology" else server.request(
                "lesson", {"graph": graph, "node_id": node["id"]})
            assert lesson["source"] == "curated_example" and lesson["math_context"] == context, "matching-example-card-context"
            assert lesson["definition"].strip() and lesson["proof_idea"].strip() and lesson["illustration"], "complete-offline-card"
            cards = server.request("study/tasks", {"graph": graph, "node_id": node["id"], "kind": "lesson", "lesson": lesson})["tasks"]
            retrieval = server.request("study/tasks", {"graph": graph, "node_id": node["id"], "kind": "retrieval", "lesson": lesson})["tasks"]
            assert retrieval and all(task in cards for task in retrieval), "retrieval-filter-matches-card-tasks"
            for task in cards:
                expected_source = "local_adaptation" if task["kind"] == "retrieval" else "curated_example"
                assert task["id"] not in task_ids and task["source"] == expected_source, "unique-offline-card-task"
                task_ids.add(task["id"])
            choice = next(task for task in cards if task["format"] == "choice")
            feedback = server.request("study/feedback", {"graph": graph, "node_id": node["id"], "task_id": choice["id"],
                "answer": str(choice["correct_index"]), "hint_level": 0, "lesson": lesson, "use_model": False})
            assert feedback["outcome"] == "correct" and not feedback["review_required"], "verified-example-choice-answer"
            independent = next(task for task in cards if task["kind"] == "independent")
            assert independent["reference_answer"].strip() and independent["rubric"], "proof-reference-and-rubric"
            card_count += 1
        if item["id"] == "rank_nullity":
            assert "有限维" in context and "实数域" in context and "(-1,-1,1)" in context, "rank-nullity-real-finite-context"
            target_card = server.request("lesson", {"graph": graph, "node_id": graph["target_id"]})
            assert "张成" in target_card["proof_idea"] and "独立" in target_card["proof_idea"], "rank-nullity-basis-proof"
        elif item["id"] == "epsilon_delta":
            assert "聚点" in context and "0<|x−a|" in context, "epsilon-delta-domain-context"
            target_card = server.request("lesson", {"graph": graph, "node_id": graph["target_id"]})
            proof = target_card["proof_idea"].replace("\\varepsilon", "ε").replace(" ", "")
            assert "ε/2" in proof and "任意" in proof, "epsilon-delta-positive-choice-proof"
    assert card_count == 20 and len(task_ids) == 135, "all-offline-cards-and-tasks"
    return {"multiple_curated_examples": True, "curated_example_count": len(catalog),
            "all_curated_cards": card_count, "all_curated_tasks": len(task_ids)}


def _check_full_backup(server: LocalServer, graph: dict, lesson: dict, task: dict, chat_turns: list) -> dict:
    """Complete learning interchange, with isolated API settings kept outside it."""
    node_id = lesson["node_id"]
    project = server.request("library/projects", {"title": "完整备份自检项目"})
    timestamp = datetime.now(timezone.utc).isoformat()
    state = {"mastery": {node_id: {"definition": True, "intuition": True, "application": False}},
        "lessons": {node_id: lesson}, "notes": {node_id: "完整备份中的合成笔记"}, "chat_turns": chat_turns,
        "attempts": [{"id": str(uuid4()), "node_id": node_id, "task_id": task["id"], "answer": str(task["correct_index"]),
            "hint_level": 0, "attempt_type": "exercise", "outcome": "independent", "created_at": timestamp, "task": task}],
        "reviews": {node_id: {"due_at": timestamp, "last_attempt_at": timestamp, "interval_days": 1, "streak": 1}},
        "graph_source": "example", "study_mode": "proof", "active_node_id": node_id}
    history = server.request("library/histories", {"title": "完整备份自检历史", "goal": "完整备份的合成目标",
        "project_id": project["id"], "graph": graph, "state": state})
    problem = server.request("library/problems", {"history_id": history["id"], "node_id": node_id,
        "question": "完整备份中的合成未解决问题", "response": "保留原始回答快照", "reason": "user_marked"})
    backup = server.request("library/backup")
    assert set(backup) == {"format", "version", "created_at", "projects", "histories", "problems"}, "learning-only-backup-fields"
    assert backup["format"] == "mathpath_library_backup" and backup["version"] == 1, "versioned-full-backup"
    assert backup["histories"][0]["state"] == history["state"], "backup-full-learning-state"
    assert "migration_key" not in json.dumps(backup) and "dedupe_key" not in json.dumps(backup), "backup-no-internal-fields"
    counts = {"projects": len(backup["projects"]), "histories": len(backup["histories"]), "problems": len(backup["problems"])}
    preview = server.request("library/backup/preview", backup)
    assert preview == {**counts, "already_restored": False}, "full-backup-preview-counts"
    current = server.request("library/histories", {"title": "导出后新增的本机历史", "goal": "不被恢复覆盖",
        "graph": graph, "state": {"notes": {node_id: "本机新增笔记"}}})
    before_ids = {item["id"] for item in server.request("library/histories")}
    invalid = json.loads(json.dumps(backup))
    invalid["histories"][0]["project_id"] = str(uuid4())
    try:
        server.request("library/backup/restore", invalid)
    except urllib.error.HTTPError as error:
        assert error.code == 422, "invalid-backup-validation-status"
    else:
        raise AssertionError("invalid-backup-was-restored")
    assert {item["id"] for item in server.request("library/histories")} == before_ids, "invalid-backup-no-partial-history"
    assert server.request("library/histories/" + current["id"]) == current, "invalid-backup-keeps-existing-state"
    imported = server.request("library/backup/restore", backup)
    assert imported == {**counts, "already_restored": False}, "full-backup-append-counts"
    assert server.request("library/histories/" + current["id"]) == current, "full-backup-retains-current-history"
    appended = [server.request("library/histories/" + item["id"]) for item in server.request("library/histories") if item["id"] not in before_ids]
    assert len(appended) == 1 and appended[0]["state"] == history["state"] and appended[0]["revision"] == 1, "full-backup-learning-roundtrip"
    assert appended[0]["project_id"] != project["id"] and appended[0]["created_at"] == history["created_at"], "full-backup-new-relationships-original-time"
    linked = [item for item in server.request("library/problems?status=all") if item["history_id"] == appended[0]["id"]]
    assert len(linked) == 1 and linked[0]["question"] == problem["question"] and linked[0]["created_at"] == problem["created_at"], "full-backup-problem-remapped"
    assert server.request("library/backup/restore", backup) == {**counts, "already_restored": True}, "backup-repeat-default-skipped"
    assert server.request("library/backup/preview", backup)["already_restored"], "backup-repeat-preview"
    assert server.request("library/backup/restore?repeat=true", backup) == {**counts, "already_restored": False}, "backup-explicit-repeat"
    assert len(server.request("library/histories")) == len(before_ids) + 2, "backup-explicit-repeat-adds-once"
    # Cleanup only the explicitly synthetic temporary profile; the real window
    # must start with the same empty learning collection as earlier releases.
    histories = server.request("library/histories")
    server.request("library/histories/delete", {"ids": [item["id"] for item in histories]})
    projects = server.request("library/projects")
    server.request("library/projects/delete", {"ids": [item["id"] for item in projects]})
    problems = server.request("library/problems?status=all")
    server.request("library/problems/delete", {"ids": [item["id"] for item in problems]})
    return {"full_library_backup_restore": True, "backup_repeat_protection": True,
            "backup_invalid_restore_atomic": True}


def desktop_window(server: LocalServer, directory: Path, smoke: bool = False) -> dict:
    import webview
    from webview.menu import Menu, MenuAction, MenuSeparator

    version = runtime_version()
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.settings["IGNORE_SSL_ERRORS"] = False
    window = webview.create_window(APP_NAME, server.url, width=1320, height=880,
                                   min_size=(760, 600), text_select=True,
                                   background_color="#edf1f5")
    result = {}

    def notify(message: str, title: str = APP_NAME) -> None:
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x40)

    def connect_chatgpt() -> None:
        from chatgpt_connection import start_connection
        status = start_connection()
        notify(status["message"] + "\n\n可在「模型/API 设置」选择 ChatGPT 查看登录状态。保存服务选择后才会切换模型来源。")

    menu = [Menu(APP_NAME, [
        MenuAction("模型/API 设置…", lambda: window.evaluate_js("document.getElementById('model-settings-button').click()")),
        MenuAction("连接 ChatGPT…", connect_chatgpt),
        MenuAction("使用说明", lambda: notify(
            "同调、秩—零度定理和 ε–δ 极限证明三个样例可从下拉框选择并直接学习，无需登录。\n\n"
            "新用户默认使用交大平台的 DeepSeek（deepseek-reasoner）。生成自己的学习图前，请点击「MathPath → 模型/API 设置」，填写自己的交大平台 API 密钥后保存；也可切换 ChatGPT 或其他 API。\n\n"
            "选择 ChatGPT 后，设置页会显示「登录 / 重新连接 ChatGPT」按钮；也可使用菜单「连接 ChatGPT」。两处共用一个登录流程。\n\n"
            "登录不会自动保存服务选择或生成内容。API 密钥由 Windows 加密保存，设置页不回显原文。\n\n"
            "「历史 / 项目」保存学习图、卡片、笔记、作答与复习时间；可多选移动或删除历史。删除项目会保留历史并移到未分类。\n\n"
            "开放题的本地对照只提供参考要点；模型候选反馈需要你明确点击，并仍需核对。\n\n"
            "右下角「提问」打开可移动对话框，拖动标题栏调整位置，拖动右下角改变大小；问答随当前学习历史保存。\n\n"
            "回答失败或只能给出暂定解释时，问题会进入「未解决问题」；你也可以手动保留问题，并明确标记已解决或重新打开。删除学习历史仍保留问题的原目标和知识点名称。\n\n"
            "过于宽泛的目标会先提供具体方向供选择；选择证明模式，或标记知识点的三项掌握能力后，可查看经过核对的参考书目录。\n\n"
            "学习记录保存在这台电脑的当前 Windows 用户下。「历史 / 项目」中的「完整备份学习库」保存全部项目、历史与问题；恢复时先预览数量，再确认添加，当前记录继续保留。账号与模型连接需在每台电脑单独配置。\n\n"
            "关闭应用窗口会同时停止 MathPath 本机服务。")),
        MenuSeparator(), MenuAction("退出", window.destroy),
    ])]

    def evaluate_async(script: str) -> dict:
        """Use pywebview's Promise callback and wait for its resolved result."""
        completed = threading.Event()
        returned = {}
        def resolved(value):
            returned["value"] = value
            completed.set()
        window.evaluate_js(script, callback=resolved)
        if not completed.wait(20):
            raise DesktopError("window-promise-timeout:" + sys._getframe(1).f_code.co_name)
        value = returned.get("value")
        if not isinstance(value, dict) or value.get("ok") is not True:
            failed_flags = [key for key, flag in value.items() if type(flag) is bool and not flag] if isinstance(value, dict) else []
            raise DesktopError("window-promise-check-failed:" + sys._getframe(1).f_code.co_name + ":" + ",".join(failed_flags))
        return value

    def settled_library(action: str, condition: str) -> dict:
        return evaluate_async("(async () => { try { " + action + "; "
            "const deadline = Date.now() + 15000; "
            "while (Date.now() < deadline) { "
            "if (!libraryLoading && !libraryActionBusy && (" + condition + ")) return {ok: true}; "
            "await new Promise(resolve => setTimeout(resolve, 40)); } return {ok: false}; "
            "} catch { return {ok: false}; } })()")

    def inspect_full_backup_ui() -> dict:
        """Use real download preparation, file preview, cancel and append routes."""
        checked = evaluate_async("""(async () => { try {
            await flushHistory();
            const request = async (url, value) => {
                const response = await fetch(url, value === undefined ? {cache:'no-store'} :
                    {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
                if (!response.ok) throw new Error('synthetic-backup-route-failed'); return response.json();
            };
            const originalHistory = currentHistory.id;
            const originalState = JSON.stringify(collectStudyState());
            const baseline = await request('/library/backup');
            const baselineIds = new Set(baseline.histories.map(item=>item.id));
            const originalServerHistory = await fetch('/library/histories/'+originalHistory).then(r=>r.json());
            const sourceProject = await request('/library/projects',{title:'窗口完整备份项目'});
            const sourceState = collectStudyState();
            sourceState.notes[graph.target_id] = '窗口完整备份中的原始笔记';
            const sourceHistory = await request('/library/histories',{title:'窗口完整备份源记录',goal:'窗口备份的合成目标',
                project_id:sourceProject.id,graph,state:sourceState});
            await request('/library/problems',{history_id:sourceHistory.id,node_id:graph.target_id,
                question:'窗口备份中的原始问题',response:'窗口备份的回答快照',reason:'user_marked'});
            document.getElementById('library-button').click();
            const opened = Date.now()+10000;
            while(Date.now()<opened && (libraryLoading || document.getElementById('library-panel').hidden)) await new Promise(r=>setTimeout(r,30));
            const controls = ['full-backup-button','restore-backup-button'].map(id=>document.getElementById(id));
            controls[0].scrollIntoView({block:'center'});
            const visible = controls.every(element=>{const rect=element.getBoundingClientRect(); return !element.closest('[hidden]')
                && rect.width>40 && rect.height>20 && rect.left>=0 && rect.right<=innerWidth && rect.top>=0 && rect.bottom<=innerHeight;});
            let downloadBlob = null;
            const originalUrl = URL.createObjectURL, originalClick = HTMLAnchorElement.prototype.click;
            try {
                URL.createObjectURL = function(blob) {downloadBlob=blob; return originalUrl.call(URL,blob);};
                HTMLAnchorElement.prototype.click = function() {
                    if(this.download?.startsWith('MathPath-full-backup-')) return; return originalClick.call(this);
                };
                document.getElementById('full-backup-button').click();
                const exported = Date.now()+10000;
                while(Date.now()<exported && (!downloadBlob || controls[0].disabled)) await new Promise(r=>setTimeout(r,30));
            } finally { URL.createObjectURL=originalUrl; HTMLAnchorElement.prototype.click=originalClick; }
            if(!(downloadBlob instanceof Blob)) return {ok:false};
            const backup = JSON.parse(await downloadBlob.text());
            const download = backup.format==='mathpath_library_backup' && backup.histories.some(item=>item.id===sourceHistory.id)
                && backup.projects.some(item=>item.id===sourceProject.id) && backup.problems.some(item=>item.question==='窗口备份中的原始问题')
                && !Object.hasOwn(backup,'api_key') && !Object.hasOwn(backup,'provider');
            const file = new File([JSON.stringify(backup)],'MathPath-window-backup.json',{type:'application/json'});
            const before = await request('/library/backup'); delete before.created_at;
            await previewFullBackup(file);
            const confirmation = document.getElementById('library-confirmation');
            const description = document.getElementById('library-confirm-description').textContent;
            const preview = !confirmation.hidden && description.includes(backup.projects.length+' 个项目')
                && description.includes(backup.histories.length+' 条历史') && description.includes(backup.problems.length+' 个问题')
                && description.includes('现有记录继续保留') && document.getElementById('library-confirm-yes').textContent.includes('添加');
            document.getElementById('library-confirm-no').click();
            const cancelled = await request('/library/backup'); delete cancelled.created_at;
            const cancelKeepsRecords = confirmation.hidden && JSON.stringify(cancelled)===JSON.stringify(before);
            await previewFullBackup(file); document.getElementById('library-confirm-yes').click();
            const restored = Date.now()+12000;
            while(Date.now()<restored && (libraryActionBusy || !document.getElementById('backup-message').textContent.includes('恢复完成'))) await new Promise(r=>setTimeout(r,30));
            const after = await request('/library/backup');
            const beforeIds = new Set(before.histories.map(item=>item.id));
            const copied = after.histories.filter(item=>!beforeIds.has(item.id) && item.title===sourceHistory.title);
            const retained = after.histories.find(item=>item.id===originalHistory);
            const confirm = copied.length===1 && JSON.stringify(copied[0].state)===JSON.stringify(sourceHistory.state)
                && copied[0].project_id!==sourceProject.id && after.projects.some(item=>item.id===copied[0].project_id)
                && after.problems.some(item=>item.history_id===copied[0].id && item.question==='窗口备份中的原始问题')
                && JSON.stringify(retained)===JSON.stringify(originalServerHistory) && currentHistory.id===originalHistory
                && JSON.stringify(collectStudyState())===originalState;
            await previewFullBackup(file);
            const repeatedWarning = !confirmation.hidden && document.getElementById('library-confirm-description').textContent.includes('可能产生重复记录');
            document.getElementById('library-confirm-no').click();
            await previewFullBackup({size:50*1024*1024+1,text:()=>{throw new Error('oversize-file-must-not-be-read');}});
            const oversize = document.getElementById('backup-message').textContent.includes('50 MiB') && confirmation.hidden;
            document.getElementById('library-close').click();
            const removeHistories = after.histories.filter(item=>!baselineIds.has(item.id)).map(item=>item.id);
            await request('/library/histories/delete',{ids:removeHistories});
            const baselineProjectIds = new Set(baseline.projects.map(item=>item.id));
            const removeProjects = after.projects.filter(item=>!baselineProjectIds.has(item.id)).map(item=>item.id);
            if(removeProjects.length) await request('/library/projects/delete',{ids:removeProjects});
            const baselineProblemIds = new Set(baseline.problems.map(item=>item.id));
            const removeProblems = after.problems.filter(item=>!baselineProblemIds.has(item.id)).map(item=>item.id);
            if(removeProblems.length) await request('/library/problems/delete',{ids:removeProblems});
            return {ok:visible && download && preview && cancelKeepsRecords && confirm && repeatedWarning && oversize,
                visible,download,preview,cancelKeepsRecords,confirm,repeatedWarning,oversize};
        } catch { return {ok:false}; } })()""")
        if not checked.get("ok"):
            raise DesktopError("full-backup-preview-confirm-ui-failed")
        return {"full_backup_preview_confirm_ui": True, "full_backup_cancel_keeps_records_ui": True,
                "full_backup_controls_visible": True, "full_backup_download_learning_only": True,
                "full_backup_repeat_warning_ui": True, "full_backup_oversize_rejected_ui": True}

    def inspect_example_switch_ui() -> dict:
        """Select both new examples and open their actual offline cards."""
        original = evaluate_async("""(async () => { await flushHistory(); return {ok:true,
            history:currentHistory.id,state:JSON.stringify(collectStudyState()),node:activeLessonId}; })()""")
        window.evaluate_js("(() => { if(!document.getElementById('chat-window').hidden) document.getElementById('chat-close').click(); return true; })()")
        for example_id, target_id in (("rank_nullity", "rn_rank_nullity"), ("epsilon_delta", "ed_limit_proof")):
            checked = evaluate_async("""(async () => { try {
            const select = document.getElementById('example-select');
            const catalogDeadline=Date.now()+10000;
            while(Date.now()<catalogDeadline && select.options.length!==3) await new Promise(r=>setTimeout(r,30));
            if(select.options.length!==3) return {ok:false,catalog_count:false};
            const id=__EXAMPLE_ID__, expected=__TARGET_ID__;
                select.value=id; select.dispatchEvent(new Event('change',{bubbles:true}));
                document.getElementById('example-button').click();
                const deadline=Date.now()+15000;
                while(Date.now()<deadline && (graphLoading || graph.target_id!==expected)) await new Promise(r=>setTimeout(r,30));
                if(graph.target_id!==expected || graph.nodes.length!==6) return {ok:false,map_matches:false};
                const target=[...document.querySelectorAll('.graph-node[data-node-id]')].find(item=>item.dataset.nodeId===expected);
                target?.dispatchEvent(new MouseEvent('click',{bubbles:true}));
                const cardDeadline=Date.now()+15000;
                while(Date.now()<cardDeadline && (activeLessonId!==expected || document.getElementById('lesson-panel').hidden
                    || !lessonCache.get(expected)?.lesson?.definition)) await new Promise(r=>setTimeout(r,30));
                await loadStudyTasks(document.getElementById('adaptive-practice-tasks'),'lesson',expected);
                await flushHistory();
                const panel=document.getElementById('lesson-panel');
                panel.scrollIntoView({block:'start'});
                const body=panel.querySelector('.lesson-body'),definition=document.getElementById('lesson-definition-section');
                body.scrollTop+=definition.getBoundingClientRect().top-body.getBoundingClientRect().top;
                const nodeActive=activeLessonId===expected,cardVisible=!panel.hidden;
                const svg=Boolean(document.querySelector('#lesson-illustration-viewport svg'));
                const tasks=document.querySelectorAll('#adaptive-practice-tasks .study-task').length>=2;
                const formula=Boolean(panel.querySelector('.katex'));
                const formulaErrors=panel.querySelectorAll('.katex-error').length===0;
                const noOverflow=panel.scrollWidth<=panel.clientWidth+1 && [...panel.querySelectorAll('.lesson-section p')]
                    .every(element=>element.scrollWidth<=element.clientWidth+1);
                return {ok:nodeActive && cardVisible && svg && tasks && formula && formulaErrors && noOverflow,
                    node_active:nodeActive,card_visible:cardVisible,svg_exists:svg,tasks_exist:tasks,
                    formula_exists:formula,formula_error_free:formulaErrors,no_horizontal_overflow:noOverflow};
        } catch { return {ok:false,script_exception:false}; } })()""".replace("__EXAMPLE_ID__", json.dumps(example_id))
                .replace("__TARGET_ID__", json.dumps(target_id)))
            if not checked.get("ok"):
                raise DesktopError("offline-example-switch-ui-failed")
            capture_preview(example_id)
        restored = evaluate_async("""(async () => { try {
            await openHistory(__HISTORY_ID__);
            const originalNode=__NODE_ID__;
            if(originalNode) {openLesson(originalNode); const deadline=Date.now()+10000;
                while(Date.now()<deadline && activeLessonId!==originalNode) await new Promise(r=>setTimeout(r,30));}
            return {ok:currentHistory.id===__HISTORY_ID__ && JSON.stringify(collectStudyState())===__STATE_JSON__};
        } catch {return {ok:false};} })()""".replace("__HISTORY_ID__", json.dumps(original["history"]))
            .replace("__NODE_ID__", json.dumps(original["node"]))
            .replace("__STATE_JSON__", json.dumps(original["state"])))
        if not restored.get("ok"):
            raise DesktopError("offline-example-original-history-not-restored")
        return {"offline_example_switch_ui": True, "new_example_cards_open_ui": True,
                "new_example_formulas_error_free_ui": True, "new_example_no_horizontal_overflow_ui": True}

    def capture_preview(example_id: str) -> None:
        """Optional captures contain only this synthetic WebView, never the desktop."""
        destination = os.environ.get("MATHPATH_SMOKE_CAPTURE_DIR") if smoke else None
        if not destination:
            return
        from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
        from System import Func, Object
        from System.IO import MemoryStream

        capture_dir = Path(destination).resolve()
        capture_dir.mkdir(parents=True, exist_ok=True)
        stream = MemoryStream()
        try:
            control = window.native.webview
            task = control.Invoke(Func[Object](lambda: control.CoreWebView2.CapturePreviewAsync(
                CoreWebView2CapturePreviewImageFormat.Png, stream)))
            if not task.Wait(10000):
                raise DesktopError("synthetic-webview-capture-timeout")
            capture_dir.joinpath("v050-" + example_id + "-window.png").write_bytes(bytes(stream.ToArray()))
        finally:
            stream.Dispose()

    def inspect_scope_and_books(target_id: str) -> dict:
        """Check visible choices and textbook links without confirming generation."""
        scope = evaluate_async("(async () => { try { "
            "const input = document.getElementById('goal-input'); const original = input.value; const originalHistory = currentHistory.id; const originalGoal=currentHistory.goal; "
            "const originalGraph = JSON.stringify(graph); input.value = '我想学数学'; input.dispatchEvent(new Event('input', {bubbles:true})); "
            "document.getElementById('goal-form').requestSubmit(); const deadline = Date.now() + 15000; "
            "while (Date.now() < deadline && (scopeChecking || document.getElementById('scope-panel').hidden)) await new Promise(r => setTimeout(r,40)); "
            "const panel = document.getElementById('scope-panel'); panel.scrollIntoView({block:'center'}); const rect = panel.getBoundingClientRect(); "
            "const choices = [...document.querySelectorAll('#scope-options input[type=radio]')]; const confirm = document.getElementById('scope-confirm'); "
            "const visible = !panel.hidden && getComputedStyle(panel).display !== 'none' && rect.width > 100 && rect.height > 80 "
            "&& rect.bottom > 0 && rect.top < innerHeight; const unselected = choices.every(item => !item.checked) && confirm.disabled; "
            "choices[0]?.click(); const chosen = choices[0]?.checked && !confirm.disabled && selectedScopeId === choices[0].value; "
            "document.getElementById('scope-cancel').click(); const cancelled = panel.hidden && input.value === '我想学数学' "
            "&& currentHistory.id === originalHistory && JSON.stringify(graph) === originalGraph && !graphLoading; "
            "await flushHistory(); const goalPreserved=currentHistory.goal === originalGoal; "
            "input.value = original; input.dispatchEvent(new Event('input', {bubbles:true})); "
            "return {ok: visible && unselected && chosen && cancelled && goalPreserved && choices.length >= 3 && choices.length <= 5}; "
            "} catch { return {ok:false}; } })()")
        if not scope.get("ok"):
            raise DesktopError("broad-goal-choice-cancel-ui-failed")
        books = evaluate_async("(async () => { try { "
            "const mode = document.getElementById('study-mode'); const originalMode = mode.value; "
            "mode.value = 'proof'; mode.dispatchEvent(new Event('change', {bubbles:true})); "
            "const deadline = Date.now()+15000; while(Date.now()<deadline && !document.querySelector('#goal-books-content .reference-book a')) await new Promise(r=>setTimeout(r,40)); "
            "const group=document.getElementById('goal-books'); group.scrollIntoView({block:'center'}); "
            "const link=document.querySelector('#goal-books-content .reference-book a'); const rect=link?.getBoundingClientRect(); "
            "const proof = Boolean(link && !link.closest('[hidden]') && getComputedStyle(link).visibility === 'visible' "
            "&& rect.width>30 && rect.height>10 && rect.top<innerHeight && rect.bottom>0 "
            "&& link.textContent === 'Algebraic Topology' && link.href === 'https://pi.math.cornell.edu/~hatcher/AT/ATpage.html'); "
            "mode.value='intuition'; mode.dispatchEvent(new Event('change',{bubbles:true})); document.getElementById('mastery-all').click(); "
            "const lessonDeadline=Date.now()+15000; while(Date.now()<lessonDeadline && !document.querySelector('#lesson-books-content .reference-book a')) await new Promise(r=>setTimeout(r,40)); "
            "const section=document.getElementById('lesson-books'); section.scrollIntoView({block:'center'}); const specific=document.querySelector('#lesson-books-content .reference-book a'); "
            "const specificRect=specific?.getBoundingClientRect(); const complete=Boolean(!section.hidden && specific && !specific.closest('[hidden]') "
            "&& specificRect.width>30 && specificRect.height>10 && specificRect.top<innerHeight && specificRect.bottom>0 "
            "&& specific.href === 'https://pi.math.cornell.edu/~hatcher/AT/ATpage.html' && knownIds.has(" + json.dumps(target_id) + ")); "
            "document.getElementById('mastery-clear').click(); mode.value=originalMode; mode.dispatchEvent(new Event('change',{bubbles:true})); await flushHistory(); "
            "return {ok:proof && complete && !knownIds.has(" + json.dumps(target_id) + ")}; "
            "} catch { return {ok:false}; } })()")
        if not books.get("ok"):
            raise DesktopError("reference-books-mastery-ui-failed")
        return {"goal_scope_choice_cancel_ui": True, "proof_mode_books_visible": True,
                "highest_mastery_books_visible": True}

    def inspect_unresolved_questions(original_history_id: str) -> dict:
        """Act on the two actual local replies generated by this window."""
        marked = evaluate_async("(async () => { try { const button=[...document.querySelectorAll('.chat-record-problem')].at(-1); "
            "if(!button) return {ok:false}; button.click(); const deadline=Date.now()+10000; "
            "while(Date.now()<deadline && !button.textContent.includes('已记入')) await new Promise(r=>setTimeout(r,40)); "
            "return {ok:button.textContent.includes('已记入')}; } catch {return {ok:false};} })()")
        queued = [record for record in server.request("library/problems") if record["question"].startswith("窗口自检问题")]
        if len(queued) != 2 or any(record["history_id"] != original_history_id for record in queued):
            raise DesktopError("window-local-questions-not-queued")
        if not marked.get("ok") or not any(record["reason"] == "user_marked" and "问题二" in record["question"] for record in queued):
            raise DesktopError("chat-manual-problem-record-ui-failed")
        visible = evaluate_async("(async () => { try { document.getElementById('problems-button').click(); "
            "document.getElementById('problem-search').value='窗口自检问题'; document.getElementById('problem-refresh').click(); "
            "const deadline=Date.now()+15000; while(Date.now()<deadline && problemRecords.length!==2) await new Promise(r=>setTimeout(r,40)); "
            "const panel=document.getElementById('problem-library-content'); const rows=[...document.querySelectorAll('#problem-list .problem-record')]; "
            "rows[0]?.scrollIntoView({block:'center'}); const rect=rows[0]?.getBoundingClientRect(); "
            "return {ok:!panel.hidden && rows.length===2 && rect.width>100 && rect.height>50 && rect.top<innerHeight && rect.bottom>0 "
            "&& rows.every(row=>row.textContent.includes('窗口自检问题') && row.querySelector('details')) "
            "&& !document.querySelector('#problem-list img, #problem-list script, #problem-list iframe')}; "
            "} catch {return {ok:false};} })()")
        if not visible.get("ok"):
            raise DesktopError("unresolved-question-list-not-visible")
        resolved = evaluate_async("(async () => { try { "
            "const row=[...document.querySelectorAll('#problem-list .problem-record')].find(item=>item.querySelector('h3').textContent.includes('问题一')); "
            "[...row.querySelectorAll('button')].find(button=>button.textContent==='我已解决').click(); "
            "const deadline=Date.now()+15000; while(Date.now()<deadline && (problemBusy || problemRecords.length!==1)) await new Promise(r=>setTimeout(r,40)); "
            "if(problemRecords.length!==1 || problemRecords[0].question.includes('问题一')) return {ok:false}; "
            "const filter=document.getElementById('problem-filter'); filter.value='resolved'; filter.dispatchEvent(new Event('change',{bubbles:true})); "
            "const filterDeadline=Date.now()+15000; while(Date.now()<filterDeadline && !(problemRecords.length===1 && problemRecords[0].status==='resolved')) await new Promise(r=>setTimeout(r,40)); "
            "const resolvedRow=document.querySelector('#problem-list .problem-record'); const button=[...resolvedRow.querySelectorAll('button')].find(item=>item.textContent==='重新打开'); "
            "button.scrollIntoView({block:'center'}); const rect=button.getBoundingClientRect(); const visible=rect.width>40 && rect.height>20 && rect.top<innerHeight && rect.bottom>0; "
            "button.click(); const reopenDeadline=Date.now()+15000; while(Date.now()<reopenDeadline && (problemBusy || problemRecords.length!==0)) await new Promise(r=>setTimeout(r,40)); "
            "filter.value='open'; filter.dispatchEvent(new Event('change',{bubbles:true})); const openDeadline=Date.now()+15000; "
            "while(Date.now()<openDeadline && problemRecords.length!==2) await new Promise(r=>setTimeout(r,40)); "
            "document.getElementById('library-close').click(); return {ok:visible && problemRecords.length===2 && document.getElementById('library-panel').hidden}; "
            "} catch {return {ok:false};} })()")
        queued = [record for record in server.request("library/problems") if record["question"].startswith("窗口自检问题")]
        if not resolved.get("ok") or len(queued) != 2 or any(record["status"] != "open" for record in queued):
            raise DesktopError("unresolved-question-resolve-reopen-ui-failed")
        return {"unresolved_questions_visible": True, "unresolved_manual_record_ui": True,
                "unresolved_resolve_reopen_ui": True}

    def inspect_chat(fixture_history_id: str, target_id: str) -> dict:
        """Exercise the shipped dialog and local HTTP route in a fresh profile."""
        opened = window.evaluate_js("(() => { const launcher = document.getElementById('chat-launcher'); "
            "const rect = launcher?.getBoundingClientRect(); launcher?.click(); "
            "return {visible: Boolean(rect && rect.width > 30 && rect.height > 20), "
            "opened: Boolean(document.getElementById('chat-window') && !document.getElementById('chat-window').hidden), "
            "nonmodal: document.getElementById('chat-window')?.getAttribute('aria-modal') === 'false'}; })()")
        if not opened or not all(opened.values()):
            raise DesktopError("chat-entry-not-discoverable")
        original_history_id = window.evaluate_js("currentHistory?.id")
        if not original_history_id:
            raise DesktopError("chat-test-history-not-ready")
        local_chat = evaluate_async("(async () => { try { "
            "document.getElementById('chat-use-model').checked = false; "
            "document.getElementById('chat-context').value = " + json.dumps(target_id) + "; "
            "document.getElementById('chat-context').dispatchEvent(new Event('change', {bubbles: true})); "
            "document.getElementById('chat-question').value = '窗口自检问题一：请解释 $H_n=Z_n/B_n$ <img src=x onerror=alert(1)>。'; "
            "await sendChatQuestion(); "
            "document.getElementById('chat-question').value = '窗口自检问题二：沿用前面的符号说明取商。'; "
            "await sendChatQuestion(); await flushHistory(); "
            "const messages = document.getElementById('chat-messages'); "
            "return {ok: studyState.chat_turns.length === 2 && studyState.chat_turns.every(turn => "
            "turn.source === 'local_reference' && turn.review_required === true && turn.answer_status === 'uncertain' && turn.node_id === " + json.dumps(target_id) + "), "
            "safe: messages.querySelectorAll('img,script,iframe').length === 0, "
            "math: Boolean(messages.querySelector('.katex')), history: currentHistory.id}; "
            "} catch { return {ok: false}; } })()")
        if not local_chat.get("safe") or not local_chat.get("math") or local_chat["history"] != original_history_id:
            raise DesktopError("chat-safe-render-or-context-failed")
        saved_turns = server.request("library/histories/" + original_history_id)["state"]["chat_turns"]
        if len(saved_turns) != 2 or saved_turns[1]["question"] != "窗口自检问题二：沿用前面的符号说明取商。":
            raise DesktopError("chat-ui-turns-not-saved")
        chat_scope = evaluate_async("(async () => {try {const input=document.getElementById('chat-question'); const original=input.value; "
            "input.value='我想学数学'; input.dispatchEvent(new Event('input',{bubbles:true})); await sendChatQuestion(); "
            "const panel=document.getElementById('chat-scope-panel'); const buttons=[...document.querySelectorAll('.chat-scope-choice')]; "
            "const rect=panel.getBoundingClientRect(); const visible=!panel.hidden && rect.width>100 && rect.height>50 && buttons.length>=3 && buttons.length<=5; "
            "buttons[0]?.click(); const selected=panel.hidden && input.value!=='我想学数学' && input.value.trim() && studyState.chat_turns.length===2; "
            "input.value='我想学数学'; input.dispatchEvent(new Event('input',{bubbles:true})); await sendChatQuestion(); "
            "document.getElementById('chat-scope-cancel').click(); const cancelled=panel.hidden && input.value==='我想学数学' && studyState.chat_turns.length===2; "
            "input.value=original; input.dispatchEvent(new Event('input',{bubbles:true})); return {ok:Boolean(visible && selected && cancelled)}; "
            "}catch{return {ok:false};}})()")
        if not chat_scope.get("ok"):
            raise DesktopError("chat-broad-direction-selection-ui-failed")
        problem_checks = inspect_unresolved_questions(original_history_id)
        # Pointer events use the dialog's real handlers and actual computed
        # geometry. No fixture overrides the application functions or endpoint.
        def gesture(element_id: str, dx: int, dy: int) -> dict:
            return window.evaluate_js("(() => { const handle = document.getElementById(" + json.dumps(element_id) + "); "
                "const dialog = document.getElementById('chat-window'); const before = dialog.getBoundingClientRect(); "
                "const grip = handle.getBoundingClientRect(); const x = grip.left + Math.min(16, grip.width / 2); "
                "const y = grip.top + Math.min(16, grip.height / 2); "
                "const emit = (name, clientX, clientY) => handle.dispatchEvent(new PointerEvent(name, "
                "{bubbles: true, pointerId: 712, pointerType: 'mouse', isPrimary: true, button: 0, buttons: name === 'pointerup' ? 0 : 1, clientX, clientY})); "
                "emit('pointerdown', x, y); emit('pointermove', x + " + str(dx) + ", y + " + str(dy) + "); "
                "emit('pointerup', x + " + str(dx) + ", y + " + str(dy) + "); "
                "const after = dialog.getBoundingClientRect(); return {before: {x: before.x, y: before.y, width: before.width, height: before.height}, "
                "after: {x: after.x, y: after.y, width: after.width, height: after.height}, "
                "inside: after.left >= -1 && after.top >= -1 && after.right <= innerWidth + 1 && after.bottom <= innerHeight + 1, "
                "finished: !chatPointer}; })()")
        dragged = gesture("chat-titlebar", -120, -80)
        if (not dragged or abs(dragged["after"]["x"] - dragged["before"]["x"]) < 20
                or abs(dragged["after"]["y"] - dragged["before"]["y"]) < 20 or not dragged["finished"]):
            raise DesktopError("chat-pointer-drag-failed")
        resized = gesture("chat-resize-grip", 70, 60)
        if (not resized or resized["after"]["width"] <= resized["before"]["width"] + 10
                or resized["after"]["height"] <= resized["before"]["height"] + 10 or not resized["finished"]):
            raise DesktopError("chat-pointer-resize-failed")
        if not gesture("chat-titlebar", -10000, -10000)["inside"] or not gesture("chat-titlebar", 10000, 10000)["inside"]:
            raise DesktopError("chat-drag-boundary-failed")
        if not gesture("chat-resize-grip", 10000, 10000)["inside"]:
            raise DesktopError("chat-resize-boundary-failed")
        window.resize(760, 600)
        evaluate_async("(async () => { const deadline = Date.now() + 10000; while (Date.now() < deadline) { "
            "const rect = document.getElementById('chat-window').getBoundingClientRect(); "
            "if (innerWidth <= 760 && !document.getElementById('chat-window').hidden && rect.width >= 300 && rect.height >= 300 "
            "&& rect.left >= -1 && rect.top >= -1 && rect.right <= innerWidth + 1 && rect.bottom <= innerHeight + 1) return {ok: true}; "
            "await new Promise(resolve => setTimeout(resolve, 40)); } return {ok: false}; })()")
        window.resize(1320, 880)
        evaluate_async("(async () => { const deadline = Date.now() + 10000; while (Date.now() < deadline) { "
            "if (innerWidth > 1000) return {ok: true}; await new Promise(resolve => setTimeout(resolve, 40)); } return {ok: false}; })()")
        restored_controls = window.evaluate_js("(() => { const question = document.getElementById('chat-question'); "
            "question.value = '暂存的窗口自检草稿'; document.getElementById('chat-collapse').click(); "
            "const collapsed = chatCollapsed && question.getBoundingClientRect().height === 0; "
            "document.getElementById('chat-collapse').click(); const expanded = !chatCollapsed && question.getBoundingClientRect().height > 20; "
            "document.getElementById('chat-close').click(); const closed = document.getElementById('chat-window').hidden; "
            "document.getElementById('chat-launcher').click(); "
            "return collapsed && expanded && closed && !document.getElementById('chat-window').hidden && question.value === '暂存的窗口自检草稿'; })()")
        if not restored_controls:
            raise DesktopError("chat-collapse-close-draft-failed")
        for opening, closing in (("model-settings-button", "model-settings-close"), ("library-button", "library-close")):
            interrupted = window.evaluate_js("(() => { document.getElementById(" + json.dumps(opening) + ").click(); "
                "const hidden = document.getElementById('chat-window').hidden; document.getElementById(" + json.dumps(closing) + ").click(); "
                "return hidden && !document.getElementById('chat-window').hidden; })()")
            if not interrupted:
                raise DesktopError("chat-modal-interruption-failed")
        evaluate_async("(async () => { try { await openHistory(" + json.dumps(fixture_history_id) + "); "
            "return {ok: studyState.chat_turns.length === 0 && !document.getElementById('chat-messages').textContent.includes('窗口自检问题一')}; "
            "} catch { return {ok: false}; } })()")
        evaluate_async("(async () => { try { await openHistory(" + json.dumps(original_history_id) + "); "
            "return {ok: studyState.chat_turns.length === 2 && document.getElementById('chat-messages').textContent.includes('窗口自检问题二')}; "
            "} catch { return {ok: false}; } })()")
        return {"chat_entry_visible": True, "chat_nonmodal_dialog": True,
                "chat_local_two_turns": True, "chat_context_snapshot": True,
                "chat_safe_formula_render": True, "chat_drag_ui": True,
                "chat_resize_ui": True, "chat_viewport_clamp": True,
                "chat_collapse_reopen": True, "chat_modal_interruption": True,
                "chat_history_restore_ui": True, "chat_broad_scope_choice_ui": True, **problem_checks}

    def inspect_window():
        try:
            if not window.events.loaded.wait(20):
                raise DesktopError("应用窗口未能载入页面。")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                observed = window.evaluate_js("({title: document.title, nodes: document.querySelectorAll('.graph-node[data-node-id]').length, "
                    "scripts: [...document.scripts].some(s => s.src.includes('/static/app.js')), "
                    "ready: Boolean(document.getElementById('target-label').textContent.trim()) && !['正在载入…', '等待学习图'].includes(document.getElementById('target-label').textContent.trim()), "
                    "renderer: navigator.userAgent.includes('Edg/')})")
                if observed and observed.get("ready") and observed.get("scripts") and observed.get("nodes", 0) >= 2 and observed.get("renderer"):
                    break
                time.sleep(.2)
            else:
                raise DesktopError("page-not-ready")
            target_id = server.request("example")["target_id"]
            window.evaluate_js("(() => { const target = [...document.querySelectorAll('.graph-node[data-node-id]')]"
                ".find(node => node.dataset.nodeId === " + json.dumps(target_id) + "); "
                "if (!target) throw new Error('target-not-found'); "
                "target.dispatchEvent(new MouseEvent('click', {bubbles: true})); return true; })()")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                card = window.evaluate_js("({opened: !document.getElementById('lesson-panel').hidden, "
                    "numbered: /^知识点 [0-9]+ · /.test(document.getElementById('lesson-title').textContent), "
                    "followups: document.querySelectorAll('#followup-list .followup-item').length, "
                    "illustration: document.querySelector('#lesson-illustration-viewport svg')?.getAttribute('viewBox') === '0 0 640 360', "
                    "prerequisites: document.querySelectorAll('.prerequisite-item[data-prerequisite-id]').length})")
                if (card and card.get("opened") and card.get("numbered") and card.get("followups", 0) >= 2
                        and card.get("illustration") and card.get("prerequisites", 0) >= 1):
                    break
                time.sleep(.2)
            else:
                raise DesktopError("enriched-card-not-ready")
            practice = evaluate_async("(async () => { try { "
                "await loadStudyTasks(document.getElementById('adaptive-practice-tasks'), 'lesson', activeLessonId); "
                "await flushHistory(); "
                "return {ok: Boolean(document.querySelectorAll('#adaptive-practice-tasks .study-task').length >= 2), "
                "tasks: document.querySelectorAll('#adaptive-practice-tasks .study-task').length, "
                "katex: Boolean(window.katex && window.katex.renderToString('H_n=Z_n/B_n', {throwOnError: true}).includes('katex'))}; "
                "} catch { return {ok: false}; } })()")
            if not practice.get("katex"):
                raise DesktopError("offline-katex-renderer-not-ready")
            guidance_checks = inspect_scope_and_books(target_id)
            window.evaluate_js("document.querySelector('.prerequisite-toggle').click()")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                preview = window.evaluate_js("(() => { const content = document.querySelector('.prerequisite-preview-content'); "
                    "return Boolean(content && !content.hidden && content.textContent.length > 50); })()")
                if preview:
                    break
                time.sleep(.2)
            else:
                raise DesktopError("prerequisite-preview-not-ready")
            window.evaluate_js("document.getElementById('model-settings-button').click()")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                settings = window.evaluate_js("(() => { const panel = document.getElementById('model-settings-panel'); "
                    "const key = document.getElementById('model-api-key'); "
                    "return {opened: Boolean(panel && !panel.hidden), password: key?.type === 'password', "
                    "key_empty: key?.value === '', "
                    "saved_metadata: document.getElementById('model-provider')?.value === 'api' "
                    "&& document.getElementById('model-base-url')?.value === 'https://example.invalid/v1' "
                    "&& document.getElementById('model-model')?.value === 'offline-test-model', "
                    "close: Boolean(document.getElementById('model-settings-close'))}; })()")
                if (settings and settings.get("opened") and settings.get("password")
                        and settings.get("key_empty") and settings.get("saved_metadata") and settings.get("close")):
                    break
                time.sleep(.2)
            else:
                raise DesktopError("api-settings-not-ready")
            previous_settings = server.request("settings/model")
            preset = window.evaluate_js("(() => { const preset = document.getElementById('model-api-preset'); "
                "if (!preset) return {visible: false}; preset.scrollIntoView({block:'center'}); "
                "const rect = preset.getBoundingClientRect(); const visible = !preset.closest('[hidden]') "
                "&& rect.width > 40 && rect.height > 20 && rect.top >= 0 && rect.bottom <= innerHeight; "
                "const named = [...preset.options].some(option => option.value === 'sjtu_deepseek' "
                "&& option.textContent.includes('DeepSeek') && option.textContent.includes('交大')); "
                "preset.value = 'sjtu_deepseek'; preset.dispatchEvent(new Event('change', {bubbles: true})); "
                "return {visible, named, fields: document.getElementById('model-provider').value === 'api' "
                "&& document.getElementById('model-base-url').value === 'https://models.sjtu.edu.cn/api/v1' "
                "&& document.getElementById('model-model').value === 'deepseek-reasoner' "
                "&& document.getElementById('model-api-format').value === 'chat_completions' "
                "&& document.getElementById('model-output-mode').value === 'json_object', "
                "key_required: document.getElementById('model-api-key').required "
                "&& document.getElementById('model-api-key').value === ''}; })()")
            if not preset or not all(preset.values()):
                raise DesktopError("deepseek-preset-not-discoverable")
            if server.request("settings/model") != previous_settings:
                raise DesktopError("deepseek-preset-was-saved-automatically")
            window.evaluate_js("(() => { const provider = document.getElementById('model-provider'); "
                "provider.value = 'chatgpt'; provider.dispatchEvent(new Event('change', {bubbles: true})); return true; })()")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                login = window.evaluate_js("(() => { const button = document.getElementById('chatgpt-login-button'); "
                    "const status = document.getElementById('chatgpt-login-status'); "
                    "const rect = button?.getBoundingClientRect(); const style = button ? getComputedStyle(button) : null; "
                    "return {visible: Boolean(button && !button.closest('[hidden]') && style.visibility === 'visible' "
                    "&& style.display !== 'none' && rect.width > 40 && rect.height > 20), "
                    "in_view: Boolean(rect && rect.top >= 0 && rect.left >= 0 && rect.bottom <= innerHeight && rect.right <= innerWidth), "
                    "label: Boolean(button?.textContent.includes('ChatGPT') && button.textContent.includes('登录')), "
                    "status: Boolean(status?.getAttribute('role') === 'status' && status.textContent.trim()), "
                    "enabled: Boolean(button && !button.disabled)}; })()")
                if (login and login.get("visible") and login.get("in_view") and login.get("label")
                        and login.get("status") and login.get("enabled")):
                    break
                time.sleep(.2)
            else:
                raise DesktopError("chatgpt-login-button-not-discoverable")
            connection = server.request("settings/chatgpt/status")
            if connection["status"] != "idle" or connection["attempt"] != 0:
                raise DesktopError("unexpected-chatgpt-login-attempt")
            if server.request("settings/model")["provider"] != "api":
                raise DesktopError("service-choice-was-saved-automatically")
            window.evaluate_js("document.getElementById('model-settings-close').click()")
            if not window.evaluate_js("document.getElementById('model-settings-panel').hidden"):
                raise DesktopError("api-settings-did-not-close")
            # The browser profile and database are both fresh temporary test data.
            # Create the test project through the real UI and act only on these
            # two explicitly named records, leaving the displayed sample intact.
            fixture_graph = server.request("example")
            fixture_histories = [server.request("library/histories", {
                "title": "窗口自检历史 " + letter, "goal": "窗口内的合成学习记录", "graph": fixture_graph,
                "state": {"graph_source": "example", "notes": {target_id: "用于验证项目删除保留的笔记"}}})
                for letter in ("A", "B")]
            chat_checks = inspect_chat(fixture_histories[0]["id"], target_id)
            settled_library("document.getElementById('library-button').click()", "libraryHistories.length >= 2")
            library_ui = window.evaluate_js("(() => { const panel = document.getElementById('library-panel'); "
                "const rect = document.getElementById('library-button').getBoundingClientRect(); "
                "return {opened: !panel.hidden, entry: rect.width > 40 && rect.height > 20, "
                "history_checks: document.querySelectorAll('#history-list input[type=checkbox]').length >= 2}; })()")
            if not library_ui or not all(library_ui.values()):
                raise DesktopError("library-entry-not-discoverable")
            window.evaluate_js("document.getElementById('manage-projects').click()")
            settled_library("document.getElementById('project-create-title').value = '窗口自检项目'; "
                "document.getElementById('project-create-form').requestSubmit()",
                "libraryProjects.some(item => item.title === '窗口自检项目')")
            project = next(item for item in server.request("library/projects") if item["title"] == "窗口自检项目")
            project_ui = window.evaluate_js("(() => { const panel = document.getElementById('project-management'); "
                "const check = document.querySelector('#project-manage-list input[type=checkbox]'); "
                "return !panel.hidden && Boolean(check && check.getBoundingClientRect().width > 0); })()")
            if not project_ui:
                raise DesktopError("project-selection-not-visible")
            select_fixtures = "for (const row of document.querySelectorAll('#history-list .history-row')) { "
            select_fixtures += "if (/^窗口自检历史 [AB]$/.test(row.querySelector('.history-open').textContent)) { "
            select_fixtures += "const check = row.querySelector('input[type=checkbox]'); check.checked = true; check.dispatchEvent(new Event('change', {bubbles: true})); } }"
            window.evaluate_js("(() => { " + select_fixtures + "; return true; })()")
            settled_library("document.getElementById('move-history-project').value = " + json.dumps(project["id"]) + "; "
                "document.getElementById('move-histories').click()",
                "libraryHistories.filter(item => /^窗口自检历史 [AB]$/.test(item.title)).every(item => item.project_id === " + json.dumps(project["id"]) + ")")
            if not all(server.request("library/histories/" + item["id"])["project_id"] == project["id"] for item in fixture_histories):
                raise DesktopError("ui-batch-move-not-saved")
            window.evaluate_js("(() => { const row = [...document.querySelectorAll('#project-manage-list .project-manage-row')]"
                ".find(item => item.querySelector('label span')?.textContent === '窗口自检项目'); "
                "const check = row?.querySelector('input[type=checkbox]'); if (!check) throw new Error('missing-fixture-project'); "
                "check.checked = true; check.dispatchEvent(new Event('change', {bubbles: true})); "
                "document.getElementById('delete-projects').click(); return true; })()")
            if not window.evaluate_js("!document.getElementById('library-confirmation').hidden && "
                    "document.getElementById('library-confirm-description').textContent.includes('历史都会保留')"):
                raise DesktopError("project-delete-retention-confirmation-missing")
            settled_library("document.getElementById('library-confirm-yes').click()", "libraryProjects.length === 0")
            kept = [server.request("library/histories/" + item["id"]) for item in fixture_histories]
            if not all(item["project_id"] is None and item["state"]["notes"][target_id] == "用于验证项目删除保留的笔记" for item in kept):
                raise DesktopError("ui-project-delete-did-not-retain-history")
            window.evaluate_js("(() => { " + select_fixtures + "; document.getElementById('delete-histories').click(); return true; })()")
            if not window.evaluate_js("!document.getElementById('library-confirmation').hidden"):
                raise DesktopError("history-delete-confirmation-missing")
            settled_library("document.getElementById('library-confirm-yes').click()",
                "!libraryHistories.some(item => /^窗口自检历史 [AB]$/.test(item.title))")
            if any(item["id"] in {record["id"] for record in server.request("library/histories")} for item in fixture_histories):
                raise DesktopError("ui-batch-history-delete-not-saved")
            window.evaluate_js("document.getElementById('library-close').click()")
            if not window.evaluate_js("document.getElementById('library-panel').hidden"):
                raise DesktopError("library-did-not-close")
            backup_window_checks = inspect_full_backup_ui()
            example_window_checks = inspect_example_switch_ui()
            result.update({"window": "ok", "webview2": version, "dom_loaded": True,
                           "dom_nodes": observed["nodes"], "numbered_lesson": True,
                           "followup_exercises": card["followups"], "illustration": True,
                           "prerequisite_items": card["prerequisites"], "prerequisite_preview": True,
                           "api_settings_open_close": True, "api_key_password_field": True,
                           "api_key_not_echoed": True, "api_settings_saved_metadata_loaded": True,
                           "api_settings_window_saves": 0,
                           "api_settings_connection_tests": 0, "chatgpt_login_button_visible": True,
                           "deepseek_preset_visible": True, "deepseek_preset_requires_platform_key": True,
                           "deepseek_preset_not_saved_automatically": True,
                           "chatgpt_login_button_in_view": True, "chatgpt_login_button_named": True,
                           "chatgpt_login_status_visible": True, "chatgpt_login_button_clicks": 0,
                           "chatgpt_login_attempts": 0, "chatgpt_authorization_started": False,
                           "service_choice_not_saved_automatically": True,
                           "practice_tasks_promises_resolved": True, "practice_tasks": practice["tasks"],
                           "offline_katex_renderer": True, "library_entry_visible": True,
                           "library_open_close": True, "history_checkboxes_visible": True,
                           "project_create_ui": True, "project_checkboxes_visible": True,
                           "history_batch_move_ui": True, "project_delete_retains_history_ui": True,
                           "history_batch_delete_ui": True})
            result.update(chat_checks)
            result.update(guidance_checks)
            result.update(backup_window_checks)
            result.update(example_window_checks)
        except Exception as exc:
            result.update({"window": "failed", "error": str(exc) if isinstance(exc, DesktopError) else type(exc).__name__})
        finally:
            window.destroy()

    # This callback tests the actual native window, then closes it automatically.
    webview.start(inspect_window if smoke else None, gui="edgechromium", debug=False,
                  private_mode=False, storage_path=str(directory / "webview"),
                  menu=menu,
                  icon=str(RESOURCE_DIR / "mathpath.ico") if (RESOURCE_DIR / "mathpath.ico").exists() else None)
    return result


def write_report(report: dict, output: str | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        Path(output).resolve().write_text(rendered + "\n", encoding="utf-8")
    if sys.stdout is not None:
        print(rendered)


def main() -> int:
    parser = argparse.ArgumentParser(description="MathPath Windows desktop application")
    parser.add_argument("--self-test", action="store_true", help="offline server/resource check; no login or model requests")
    parser.add_argument("--smoke-window", action="store_true", help="open, inspect and close a real WebView2 window")
    parser.add_argument("--report", help="write the safe release check result to this JSON file")
    args = parser.parse_args()
    testing = args.self_test or args.smoke_window
    temporary = tempfile.TemporaryDirectory(prefix="mathpath-release-check-", ignore_cleanup_errors=True) if testing else None
    directory = Path(temporary.name) if temporary else app_data_dir()
    server = None
    mutex = None
    report = {}
    code = 0
    offline_guard = None
    try:
        if os.name != "nt":
            raise DesktopError("此桌面版本支持 Windows 10/11（64 位）。")
        configure_data_dir(directory)
        if testing:
            offline_guard = OfflineBoundary()
            offline_guard.install()
        mutex = SingleInstance(directory)
        if not mutex.acquire():
            return 0
        server = LocalServer(directory, persistent=not testing)
        server.start()
        if testing:
            report.update(self_test(server))
        if args.smoke_window or not args.self_test:
            report.update(desktop_window(server, directory, smoke=args.smoke_window))
        if args.smoke_window and report.get("window") != "ok":
            report["status"] = "failed"
            code = 1
        if testing and any(offline_guard.counts.values()):
            raise DesktopError("offline-boundary-was-crossed")
    except BaseException as exc:
        code = 1
        if testing:
            report = {"status": "failed", "error": type(exc).__name__, "model_requests": 0}
        else:
            show_error(str(exc) if isinstance(exc, DesktopError) else "MathPath 未能启动。请重新打开应用或运行离线自检。")
    finally:
        if server:
            stopped = server.stop()
            if testing:
                report["server_stopped"] = stopped
                if not stopped:
                    code = 1
        if mutex:
            mutex.close()
        if offline_guard:
            report.update(offline_guard.counts)
            offline_guard.restore()
        if temporary:
            temporary.cleanup()
        if testing:
            write_report(report, args.report)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
