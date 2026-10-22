import os
import sys
import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from chatgpt_login import LoginError
from chatgpt_connection import get_connection_status, start_connection
from graph_builder import GraphError, KnowledgeGraph, NodeId, build_graph
from llm_client import ModelError, generate_text, safe_error_code
from lesson_builder import (Lesson, LessonError, build_lesson, clear_lesson_cache,
                            list_examples, load_example_graph)
from model_settings import SettingsError, get_public_settings, save_settings
from planner import LearningStatus, PlanError, current_learning_status
import library_store
from library_models import (HistoryCreate, HistoryMove, HistoryUpdate, IdBatch, Mastery,
                            BackupEnvelope, ProblemCreate, ProblemUpdate, ProjectCreate, ProjectRename)
from learning_guidance import (GoalScopeInput, ReferenceBooksInput, analyze_goal_scope,
                              get_reference_books)
from study_builder import StudyError, build_learning_feedback, get_study_plan, get_study_tasks
from teaching_help import ChatInput, HelpInput, build_learning_chat, build_learning_help

PROJECT_DIR = Path(__file__).resolve().parent
STATIC_DIR = PROJECT_DIR / "static"


class LocalStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


app = FastAPI(title="MathPath", version="0.5.1")
app.state.desktop_local_only = bool(getattr(sys, "frozen", False) or os.environ.get("MATHPATH_DESKTOP"))


@app.middleware("http")
async def desktop_origin_guard(request: Request, call_next):
    if app.state.desktop_local_only or request.url.path.startswith(("/settings/", "/library/", "/study/")):
        server = request.scope.get("server")
        port = server[1] if server else None
        expected_host = "127.0.0.1" if port == 80 else f"127.0.0.1:{port}"
        hosts = request.headers.getlist("host")
        origins = request.headers.getlist("origin")
        if hosts != [expected_host] or (origins and origins != [f"http://{expected_host}"]):
            return JSONResponse(status_code=403, content={"detail": "本机页面来源不匹配，请从 MathPath 软件打开。"})
    return await call_next(request)


app.mount("/static", LocalStaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=FileResponse, include_in_schema=False)
def home():
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html",
                        headers={"Cache-Control": "no-store"})


@app.get("/examples", include_in_schema=False)
def examples():
    return JSONResponse(list_examples(), headers={"Cache-Control": "no-store"})


@app.get("/example", response_model=KnowledgeGraph)
def example(example_id: Literal["homology", "rank_nullity", "epsilon_delta"] = "homology"):
    return invoke_model(load_example_graph, example_id)

class GoalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=5000)
    mode: Literal["intuition", "application", "proof"] | None = None

    @field_validator("text")
    @classmethod
    def strip_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("请输入数学学习目标或一小段数学文本")
        return value


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    graph: KnowledgeGraph
    known_ids: list[NodeId] = Field(default_factory=list, max_length=12)
    mode: Literal["intuition", "application", "proof", "repair"] | None = None
    mastery: dict[NodeId, Mastery] = Field(default_factory=dict, max_length=12)


class LessonInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    graph: KnowledgeGraph
    node_id: NodeId

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/analyze", response_model=KnowledgeGraph)
def analyze(body: GoalInput):
    return (invoke_model(build_graph, body.text, mode=body.mode) if body.mode is not None
            else invoke_model(build_graph, body.text))


def invoke_model(builder, *args, **kwargs):
    try:
        return builder(*args, **kwargs)
    except (LoginError, ModelError, SettingsError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except (GraphError, LessonError, StudyError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except APITimeoutError:
        raise HTTPException(status_code=504, detail="模型请求超时，请稍后重试") from None
    except APIConnectionError:
        raise HTTPException(status_code=502, detail="无法连接当前模型服务，请检查网络或接口地址") from None
    except APIStatusError as exc:
        code = safe_error_code(exc.code)
        raise HTTPException(status_code=502, detail=f"当前模型服务返回 HTTP {exc.status_code}，错误代码：{code}") from None
    except APIError as exc:
        raise HTTPException(status_code=502, detail="模型请求失败，错误代码：" + safe_error_code(exc.code)) from None


@app.get("/settings/model", include_in_schema=False)
def model_settings():
    try:
        return JSONResponse(get_public_settings(), headers={"Cache-Control": "no-store"})
    except SettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.post("/settings/model", include_in_schema=False)
async def update_model_settings(request: Request):
    # Parse here to avoid FastAPI validation errors echoing a submitted secret.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 32_768:
            raise HTTPException(status_code=413, detail="模型配置内容过长，请检查输入。")
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        raise HTTPException(status_code=400, detail="模型配置格式无效，请检查输入。") from None
    try:
        result = save_settings(value)
    except SettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    clear_lesson_cache()
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.post("/settings/model/test", include_in_schema=False)
def test_model_settings():
    # Explicit user action only; never called automatically when saving settings.
    invoke_model(generate_text, "请只回答：MathPath 连接成功。", instructions="这是连接测试，只输出指定的一句短文本。")
    return JSONResponse({"ok": True, "message": "测试完成：收到有效模型回答。"},
                        headers={"Cache-Control": "no-store"})


@app.get("/settings/chatgpt/status", include_in_schema=False)
def chatgpt_connection_status():
    return JSONResponse(get_connection_status(), headers={"Cache-Control": "no-store"})


@app.post("/settings/chatgpt/login", include_in_schema=False)
def connect_chatgpt():
    return JSONResponse(start_connection(), headers={"Cache-Control": "no-store"})


@app.post("/lesson", response_model=Lesson)
def lesson(body: LessonInput):
    if body.node_id not in {node.id for node in body.graph.nodes}:
        raise HTTPException(status_code=422, detail="学习节点不在当前图中")
    return invoke_model(build_lesson, body.graph, body.node_id)


@app.post("/plan", response_model=LearningStatus)
def plan(body: PlanInput):
    try:
        return current_learning_status(body.graph, body.known_ids, mode=body.mode, mastery=body.mastery)
    except PlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


async def local_payload(request: Request, model, *, max_bytes: int = 3_000_000):
    """Bound local writes and do not echo private answers or accidentally pasted secrets."""
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail="这次提交内容过大，请减少内容后重试。")
    try:
        value = json.loads(data)
        return model.model_validate(value)
    except (ValidationError, ValueError, UnicodeError):
        raise HTTPException(status_code=422, detail="提交内容的格式或范围不符合要求，请检查输入。") from None


def library_result(operation, *args, **kwargs):
    try:
        value = operation(*args, **kwargs)
    except library_store.LibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    return JSONResponse(value, headers={"Cache-Control": "no-store"})


@app.get("/library/projects", include_in_schema=False)
def projects():
    return library_result(library_store.list_projects)


@app.get("/library/backup", include_in_schema=False)
def full_backup():
    result = library_result(library_store.export_backup)
    result.headers["Content-Disposition"] = 'attachment; filename="MathPath-full-backup.json"'
    return result


@app.post("/library/backup/preview", include_in_schema=False)
async def preview_backup(request: Request):
    body = await local_payload(request, BackupEnvelope, max_bytes=50 * 1024 * 1024)
    return await run_in_threadpool(library_result, library_store.preview_backup, body)


@app.post("/library/backup/restore", include_in_schema=False)
async def restore_backup(request: Request, repeat: bool = False):
    body = await local_payload(request, BackupEnvelope, max_bytes=50 * 1024 * 1024)
    return await run_in_threadpool(library_result, library_store.restore_backup, body, repeat=repeat)


@app.post("/library/projects", include_in_schema=False)
async def create_project(request: Request):
    body = await local_payload(request, ProjectCreate)
    return await run_in_threadpool(library_result, library_store.create_project, body.title)


@app.patch("/library/projects/{project_id}", include_in_schema=False)
async def rename_project(project_id: str, request: Request):
    body = await local_payload(request, ProjectRename)
    return await run_in_threadpool(library_result, library_store.rename_project, project_id, body.title)


@app.post("/library/projects/delete", include_in_schema=False)
async def delete_projects(request: Request):
    body = await local_payload(request, IdBatch)
    return await run_in_threadpool(library_result, library_store.delete_projects, body.ids)


@app.get("/library/histories", include_in_schema=False)
def histories(project_id: str | None = None, query: str = Query(default="", max_length=200),
              limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0),
              uncategorized: bool = False):
    if project_id in ("uncategorized", "unfiled"):
        project_id, uncategorized = None, True
    elif project_id in ("all", ""):
        project_id = None
    return library_result(library_store.list_histories, project_id, uncategorized=uncategorized,
                          query=query, limit=limit, offset=offset)


@app.post("/library/histories", include_in_schema=False)
async def create_history(request: Request):
    body = await local_payload(request, HistoryCreate)
    return await run_in_threadpool(library_result, library_store.create_history, **body.model_dump())


@app.get("/library/histories/{history_id}", include_in_schema=False)
def history(history_id: str):
    return library_result(library_store.get_history, history_id)


@app.patch("/library/histories/{history_id}", include_in_schema=False)
async def update_history(history_id: str, request: Request):
    body = await local_payload(request, HistoryUpdate)
    return await run_in_threadpool(library_result, library_store.update_history, history_id, body)


@app.post("/library/histories/delete", include_in_schema=False)
async def delete_histories(request: Request):
    body = await local_payload(request, IdBatch)
    return await run_in_threadpool(library_result, library_store.delete_histories, body.ids)


@app.post("/library/histories/move", include_in_schema=False)
async def move_histories(request: Request):
    body = await local_payload(request, HistoryMove)
    return await run_in_threadpool(library_result, library_store.move_histories, body.ids, body.project_id)


@app.get("/library/problems", include_in_schema=False)
def problems(status: Literal["open", "resolved", "all"] = "open",
             query: str = Query(default="", max_length=200),
             limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    return library_result(library_store.list_problems, status=status, query=query, limit=limit, offset=offset)


@app.post("/library/problems", include_in_schema=False)
async def create_problem(request: Request):
    body = await local_payload(request, ProblemCreate)
    return await run_in_threadpool(library_result, library_store.create_problem, **body.model_dump())


@app.get("/library/problems/{problem_id}", include_in_schema=False)
def problem(problem_id: str):
    return library_result(library_store.get_problem, problem_id)


@app.patch("/library/problems/{problem_id}", include_in_schema=False)
async def update_problem(problem_id: str, request: Request):
    body = await local_payload(request, ProblemUpdate)
    return await run_in_threadpool(library_result, library_store.update_problem, problem_id, body.status)


@app.post("/library/problems/delete", include_in_schema=False)
async def delete_problems(request: Request):
    body = await local_payload(request, IdBatch)
    return await run_in_threadpool(library_result, library_store.delete_problems, body.ids)


@app.post("/study/scope", include_in_schema=False)
async def goal_scope(request: Request):
    body = await local_payload(request, GoalScopeInput)
    result = analyze_goal_scope(body)
    return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@app.post("/study/references", include_in_schema=False)
async def reference_books(request: Request):
    body = await local_payload(request, ReferenceBooksInput)
    result = get_reference_books(graph=body.graph, node_id=body.node_id, text=body.text)
    return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


class StudyTasksInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    graph: KnowledgeGraph
    node_id: NodeId | None = None
    kind: Literal["all", "lesson", "review", "diagnostic", "guided", "independent", "retrieval",
                  "mixed", "final", "exercise", "followup"] = "all"
    lesson: Lesson | None = None


class StudyFeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    graph: KnowledgeGraph
    node_id: NodeId
    task_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_-]+$")
    answer: str = Field(min_length=1, max_length=6000)
    hint_level: int = Field(default=0, ge=0, le=3)
    lesson: Lesson | None = None
    use_model: bool = False


@app.post("/study/tasks", include_in_schema=False)
async def study_tasks(request: Request):
    body = await local_payload(request, StudyTasksInput)
    tasks = invoke_model(get_study_tasks, body.graph, body.node_id, body.kind, lesson=body.lesson)
    study_plan = invoke_model(get_study_plan, body.graph)
    return JSONResponse({"tasks": [task.model_dump(mode="json") for task in tasks],
                         "study_plan": study_plan.model_dump(mode="json")},
                        headers={"Cache-Control": "no-store"})


@app.post("/study/feedback", include_in_schema=False)
async def study_feedback(request: Request):
    body = await local_payload(request, StudyFeedbackInput)
    feedback = await run_in_threadpool(invoke_model, build_learning_feedback, body.graph, body.node_id,
        body.task_id, body.answer, body.hint_level, lesson=body.lesson, use_model=body.use_model)
    return JSONResponse(feedback.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@app.post("/study/help", include_in_schema=False)
async def study_help(request: Request):
    body = await local_payload(request, HelpInput)
    result = await run_in_threadpool(invoke_model, build_learning_help, body)
    return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@app.post("/study/chat", include_in_schema=False)
async def study_chat(request: Request):
    body = await local_payload(request, ChatInput)
    try:
        result = await run_in_threadpool(invoke_model, build_learning_chat, body)
    except HTTPException as error:
        problem_id, save_failed = await record_chat_problem(body, "", "model_failure")
        return JSONResponse(status_code=error.status_code,
            content={"detail": error.detail, "problem_id": problem_id, "problem_save_failed": save_failed},
            headers={"Cache-Control": "no-store"})
    problem_id, save_failed = None, False
    if result.answer_status in ("uncertain", "unanswered"):
        problem_id, save_failed = await record_chat_problem(body, result.response, "uncertain")
    return JSONResponse({**result.model_dump(mode="json"), "problem_id": problem_id,
                         "problem_save_failed": save_failed}, headers={"Cache-Control": "no-store"})


async def record_chat_problem(body: ChatInput, response: str, reason: str) -> tuple[str | None, bool]:
    """Keep the submitted learning snapshot even if its original history was deleted."""
    graph = body.graph
    node = next((item for item in graph.nodes if item.id == body.node_id), None) if graph else None
    target = next((item for item in graph.nodes if item.id == graph.target_id), None) if graph else None
    goal = graph.study_plan.objective if graph and graph.study_plan else target.label if target else "自由提问"
    payload = {"history_id": body.history_id, "node_id": body.node_id, "goal": goal[:5000],
               "node_label": node.label[:300] if node else "", "question": body.question,
               "response": response, "reason": reason}
    try:
        result = await run_in_threadpool(library_store.create_problem, **payload)
        return result["id"], False
    except library_store.LibraryNotFound:
        payload["history_id"] = None
        try:
            result = await run_in_threadpool(library_store.create_problem, **payload)
            return result["id"], False
        except library_store.LibraryError:
            return None, True
    except library_store.LibraryError:
        return None, True
