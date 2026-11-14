"""Bounded, local-only classroom routes; the app applies the origin guard."""
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.requests import ClientDisconnect
from starlette.concurrency import run_in_threadpool
from pydantic import ValidationError

import lecture_store as store
import lecture_tutor as tutor

router = APIRouter(prefix="/lectures", tags=["classroom"])


async def tutor_payload(request, model):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 65536:
            raise HTTPException(status_code=413, detail="课堂提问或作答过长，请缩短后重试。")
    try:
        return model.model_validate_json(data)
    except (ValidationError, ValueError, UnicodeError):
        raise HTTPException(status_code=422, detail="课堂提问或作答格式无效，请检查输入。") from None


async def tutor_result(operation, *args):
    try:
        return await run_in_threadpool(operation, *args)
    except store.LectureError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from None
    except Exception:
        raise HTTPException(status_code=502, detail="课堂诊断未完成，请检查 MathPath 当前数学模型的配置或网络。已保存的记录保留，可先刷新诊断历史。") from None


@router.get("/{job_id}/tutor")
def tutor_history(job_id: str):
    return JSONResponse(result(tutor.sessions, job_id), headers={"Cache-Control": "no-store"})


@router.post("/{job_id}/tutor")
async def diagnose_lecture(job_id: str, request: Request):
    body = await tutor_payload(request, tutor.Input)
    return JSONResponse(await tutor_result(tutor.diagnose, job_id, body), headers={"Cache-Control": "no-store"})


@router.post("/{job_id}/tutor/{session_id}/answer")
async def answer_lecture(job_id: str, session_id: str, request: Request):
    body = await tutor_payload(request, tutor.AnswerInput)
    return JSONResponse(await tutor_result(tutor.answer, job_id, session_id, body), headers={"Cache-Control": "no-store"})


@router.delete("/{job_id}/tutor/{session_id}")
def remove_tutor_session(job_id: str, session_id: str):
    return result(tutor.delete_session, job_id, session_id)


def result(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except store.LectureError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from None


async def payload(request):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 16_384:
            raise HTTPException(status_code=413, detail="视频模型设置内容过长，请检查输入。")
    try:
        value = json.loads(data)
        if not isinstance(value, dict) or set(value) - {"api_key", "model", "chunk_seconds", "remote_upload_confirmed"}:
            raise ValueError
        return value
    except (ValueError, UnicodeError):
        raise HTTPException(status_code=422, detail="视频模型设置格式不正确，请检查输入。") from None


@router.get("")
def list_lectures():
    return JSONResponse(result(store.list_jobs), headers={"Cache-Control": "no-store"})


@router.post("")
async def upload_lecture(request: Request, filename: str = Query(min_length=1, max_length=180),
                         duration_seconds: float | None = None):
    content_length = request.headers.get("content-length")
    try:
        expected_size = int(content_length) if content_length is not None else None
    except ValueError:
        raise HTTPException(status_code=422, detail="视频上传大小无效。") from None
    mime_type = result(store.validate_upload, filename, request.headers.get("content-type", ""),
                       expected_size, duration_seconds)
    directory = result(store.begin_upload, filename, mime_type, expected_size, duration_seconds)
    size = 0
    digest = hashlib.sha256()
    try:
        with (directory / "video.part").open("xb") as handle:
            async for chunk in request.stream():
                size += len(chunk)
                if size > store.MAX_VIDEO_BYTES:
                    raise store.LectureError("视频超过 2 GiB，请分课时上传。", 413)
                digest.update(chunk)
                handle.write(chunk)
        if size == 0 or (expected_size is not None and size != expected_size):
            raise store.LectureError("视频上传未完整结束，请重新上传。", 422)
        job = store.finish_upload(directory, filename, mime_type, size, digest.hexdigest(), duration_seconds)
        return JSONResponse(job, status_code=201, headers={"Cache-Control": "no-store"})
    except ClientDisconnect:
        store.abort_upload(directory)
        raise HTTPException(status_code=400, detail="视频上传已中断，请重新上传。") from None
    except store.LectureError as error:
        store.abort_upload(directory)
        raise HTTPException(status_code=error.status_code, detail=str(error)) from None
    except OSError:
        store.abort_upload(directory)
        raise HTTPException(status_code=503, detail="视频无法保存，请检查磁盘空间后重试。") from None
    except BaseException:
        store.abort_upload(directory)
        raise


@router.get("/{job_id}")
def get_lecture(job_id: str):
    return JSONResponse(result(store.get_job, job_id), headers={"Cache-Control": "no-store"})


@router.get("/{job_id}/video")
def lecture_video(job_id: str):
    job = result(store.get_job, job_id)
    return FileResponse(result(store.video_path, job_id), media_type=job["mime_type"],
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/{job_id}/analyze")
async def analyze_lecture(job_id: str, request: Request):
    values = await payload(request)
    if "api_key" not in values or "model" not in values:
        raise HTTPException(status_code=422, detail="请填写视频模型名称和 API 密钥。")
    return JSONResponse(result(store.start_analysis, job_id, **values), status_code=202,
                        headers={"Cache-Control": "no-store"})


@router.post("/{job_id}/cancel")
def cancel_lecture(job_id: str):
    return JSONResponse(result(store.cancel_analysis, job_id), headers={"Cache-Control": "no-store"})


@router.delete("/{job_id}")
def delete_lecture(job_id: str):
    return result(store.delete_job, job_id)


@router.get("/{job_id}/export")
def export_lecture(job_id: str, format: Literal["json", "markdown"] = "json"):
    content = result(store.export_job, job_id, format)
    suffix, mime = ("json", "application/json") if format == "json" else ("md", "text/markdown")
    return Response(content, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="MathPath-classroom-{job_id}.{suffix}"',
                             "Cache-Control": "no-store"})
