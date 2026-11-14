"""Local classroom video jobs; explicit model requests and resumable partial reports.

Only lecture material is persisted. Video API keys and remote upload handles exist
in a worker's memory for that explicit run and never enter metadata or exports.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import threading
from uuid import uuid4

from lecture_models import validate_clip
import lecture_provider

MAX_VIDEO_BYTES = 2 * 1024**3
MAX_DURATION_SECONDS = 3 * 3600
MAX_REPORT_BYTES = 64 * 1024**2
MAX_CLIP_BYTES = 512 * 1024
MAX_JOBS = 500
ACTIVE = frozenset({"queued", "uploading_remote", "processing_remote", "analyzing", "cleaning_remote"})
ID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MODEL_PATTERN = re.compile(r"^gemini-[a-z0-9][a-z0-9._-]{0,119}$")
VIDEO_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
               ".mov": "video/quicktime", ".avi": "video/avi"}
_lock = threading.RLock()
_active = {}
_uploads = set()
_executor = None
_PUBLIC = ("id", "filename", "mime_type", "size_bytes", "video_sha256", "created_at", "updated_at",
           "status", "estimated_duration_seconds", "duration_seconds", "model", "chunk_seconds",
           "analysis_config", "completed_chunks", "total_chunks", "processed_seconds", "coverage_ratio",
           "error", "cleanup_failed", "source", "review_required", "clips")


class LectureError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def data_root():
    configured = os.environ.get("MATHPATH_DATA_DIR")
    base = Path(configured).expanduser().resolve() if configured else Path(__file__).resolve().parent
    return base / ".mathpath" / "lectures"


def job_directory(job_id):
    if not isinstance(job_id, str) or not ID_PATTERN.fullmatch(job_id):
        raise LectureError("课堂记录不存在。", 404)
    root = data_root().resolve()
    directory = root / job_id
    if directory.is_symlink() or directory.resolve().parent != root:
        raise LectureError("课堂记录路径无效。", 404)
    return directory


def _storage_error():
    return LectureError("课堂文件暂时无法读取或保存，请检查本机磁盘空间后重试。", 503)


def _json_bytes(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise _storage_error() from None
    if len(encoded) > MAX_REPORT_BYTES:
        raise LectureError("课堂解析记录超过本机保存上限，已保留先前成功的片段。", 413)
    return encoded


def _save(directory, job):
    job["updated_at"] = _now()
    encoded = _json_bytes({key: job[key] for key in _PUBLIC})
    temporary = directory / ("metadata-" + uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(directory / "metadata.json")
    except OSError:
        raise _storage_error() from None
    finally:
        temporary.unlink(missing_ok=True)


def _read(directory):
    path = directory / "metadata.json"
    try:
        if path.is_symlink() or path.stat().st_size > MAX_REPORT_BYTES:
            raise _storage_error()
        job = json.loads(path.read_bytes())
        if not isinstance(job, dict) or set(job) != set(_PUBLIC) or job["id"] != directory.name:
            raise _storage_error()
        # Restart recovery is explicit; reading a record never resumes billing.
        if job["status"] in ACTIVE and str(directory) not in _active:
            job["status"] = "interrupted"
            job["error"] = "上次解析在退出时中断，已保留成功片段；可明确点击继续解析。"
            _save(directory, job)
        if job["status"] == "uploading_local" and str(directory) not in _uploads:
            job["status"] = "interrupted"
            job["error"] = "上次视频上传未完成，请重新上传原视频；这条中断记录可以删除。"
            _save(directory, job)
        return job
    except FileNotFoundError:
        raise LectureError("课堂记录不存在。", 404) from None
    except (OSError, ValueError, UnicodeError, KeyError, TypeError):
        raise _storage_error() from None


def get_job(job_id, *, summary=False):
    with _lock:
        directory = job_directory(job_id)
        job = _read(directory)
        result = {key: value for key, value in job.items() if not summary or key != "clips"}
        video = directory / "video.bin"
        result["video_available"] = bool(not video.is_symlink() and video.is_file()
                                         and video.resolve().parent == directory.resolve())
        return result


def list_jobs():
    root = data_root()
    if not root.exists():
        return []
    try:
        directories = list(root.iterdir())
    except OSError:
        raise _storage_error() from None
    records = []
    for directory in directories:
        if directory.is_dir() and not directory.is_symlink() and ID_PATTERN.fullmatch(directory.name):
            try:
                records.append(get_job(directory.name, summary=True))
            except LectureError:
                # An interrupted local upload has no metadata and is not a ready video.
                continue
    return sorted(records, key=lambda item: item["created_at"], reverse=True)


def validate_upload(filename, content_type, expected_size, estimated_duration):
    if (not isinstance(filename, str) or not filename.strip() or len(filename) > 180
            or any(ord(char) < 32 for char in filename) or any(char in filename for char in "/\\:")
            or filename in {".", ".."}):
        raise LectureError("请选择文件名正常的 MP4、WebM、MOV 或 AVI 视频。", 422)
    suffix = Path(filename).suffix.lower()
    mime_type = VIDEO_TYPES.get(suffix)
    if mime_type is None:
        raise LectureError("当前支持 MP4、M4V、WebM、MOV 和 AVI 视频。", 415)
    declared = content_type.split(";", 1)[0].strip().lower()
    if declared not in {mime_type, "application/octet-stream", "", "video/x-msvideo" if suffix == ".avi" else mime_type}:
        raise LectureError("视频类型与文件扩展名不一致。", 415)
    if expected_size is not None and (type(expected_size) is not int or not 0 < expected_size <= MAX_VIDEO_BYTES):
        raise LectureError("视频大小须在 1 字节到 2 GiB 之间。", 413)
    if estimated_duration is not None and (type(estimated_duration) not in {float, int}
            or not math.isfinite(estimated_duration) or not 0 < estimated_duration <= MAX_DURATION_SECONDS):
        raise LectureError("当前课堂视频最长支持 3 小时。", 422)
    return mime_type


def begin_upload(filename, mime_type, expected_size=None, estimated_duration=None):
    with _lock:
        if len(list_jobs()) >= MAX_JOBS:
            raise LectureError("课堂记录已达到本机上限，请先导出并删除不再需要的记录。", 409)
        directory = job_directory(str(uuid4()))
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except OSError:
            raise _storage_error() from None
        now = _now()
        job = {"id": directory.name, "filename": filename, "mime_type": mime_type,
               "size_bytes": expected_size or 0, "video_sha256": "", "created_at": now, "updated_at": now,
               "status": "uploading_local", "estimated_duration_seconds": estimated_duration, "duration_seconds": None,
               "model": None, "chunk_seconds": None, "analysis_config": None,
               "completed_chunks": 0, "total_chunks": 0, "processed_seconds": 0.0, "coverage_ratio": 0.0,
               "error": None, "cleanup_failed": False, "clips": [], "source": "model_candidate",
               "review_required": True}
        _uploads.add(str(directory))
        try:
            _save(directory, job)
        except LectureError:
            _uploads.discard(str(directory))
            try:
                directory.rmdir()
            except OSError:
                pass
            raise
        return directory


def abort_upload(directory):
    # Remove only the exact, verified new upload directory and known files.
    if directory == job_directory(directory.name):
        _uploads.discard(str(directory))
        for name in ("video.part", "video.bin", "metadata.json"):
            (directory / name).unlink(missing_ok=True)
        try:
            directory.rmdir()
        except OSError:
            pass


def finish_upload(directory, filename, mime_type, size_bytes, digest, estimated_duration):
    source = directory / "video.part"
    try:
        with source.open("rb") as handle:
            header = handle.read(12)
        valid = (header[4:8] == b"ftyp" if mime_type in {"video/mp4", "video/quicktime"}
                 else header[:4] == b"\x1aE\xdf\xa3" if mime_type == "video/webm"
                 else header[:4] == b"RIFF" and header[8:12] == b"AVI ")
        if not valid:
            raise LectureError("文件未识别为对应视频容器，请重新选择原始视频。", 415)
        source.replace(directory / "video.bin")
        with _lock:
            job = _read(directory)
            job.update(status="uploaded", size_bytes=size_bytes, video_sha256=digest)
            _save(directory, job)
            _uploads.discard(str(directory))
        return get_job(directory.name)
    except OSError:
        raise _storage_error() from None


def video_path(job_id):
    get_job(job_id)
    directory = job_directory(job_id)
    path = directory / "video.bin"
    if path.is_symlink() or not path.is_file() or path.resolve().parent != directory.resolve():
        raise LectureError("本机原视频已不存在，请重新上传。", 404)
    return path


def _segments(duration, chunk_seconds):
    return [(float(index * chunk_seconds), min(float((index + 1) * chunk_seconds), duration))
            for index in range(math.ceil(duration / chunk_seconds))]


def _cancelled():
    raise LectureError("已停止后续解析，已保留此前成功的片段。", 409)


def _run(directory, api_key, model, chunk_seconds, cancel):
    remote = None
    terminal_status, terminal_error = "failed", "课堂解析未完成，已保留此前成功的片段。"
    inherited_cleanup_failure = False
    try:
        def progress(stage):
            if cancel.is_set():
                _cancelled()
            with _lock:
                job = _read(directory)
                job["status"] = stage if stage in {"uploading_remote", "processing_remote"} else "processing_remote"
                _save(directory, job)

        if cancel.is_set():
            _cancelled()
        job = get_job(directory.name)
        remote = lecture_provider.upload_video(video_path(directory.name), job["mime_type"], api_key, cancel, progress)
        duration = remote.duration_seconds
        if (type(duration) not in {int, float} or not math.isfinite(duration)
                or not 0 < duration <= MAX_DURATION_SECONDS):
            raise LectureError("视频平台未返回有效时长，或视频超过 3 小时；未开始内容解析。", 422)
        segments = _segments(float(duration), chunk_seconds)
        with _lock:
            job = _read(directory)
            if job["duration_seconds"] is not None and abs(job["duration_seconds"] - duration) > .01:
                raise LectureError("视频平台返回的时长与此前解析不一致，请重新上传后解析。", 409)
            job.update(duration_seconds=float(duration), total_chunks=len(segments), status="analyzing")
            _save(directory, job)
        for index, (start, end) in enumerate(segments):
            if cancel.is_set():
                _cancelled()
            with _lock:
                job = _read(directory)
            if index < len(job["clips"]):
                existing = job["clips"][index]
                if existing["index"] != index or existing["start_seconds"] != start or existing["end_seconds"] != end:
                    raise LectureError("已保存片段与本次时间划分不一致，请重新上传后解析。", 409)
                validate_clip(existing["analysis"], start, end)
                continue
            previous = job["clips"][-1]["analysis"]["overview"][:1600] if job["clips"] else ""
            raw = lecture_provider.analyze_clip(remote, start, end, api_key, model, cancel, previous_context=previous)
            analysis = validate_clip(raw, start, end).model_dump(mode="json")
            if len(_json_bytes(analysis)) > MAX_CLIP_BYTES:
                raise LectureError("本段解析内容超过保存上限，已保留先前片段。", 413)
            if cancel.is_set():
                _cancelled()
            with _lock:
                job = _read(directory)
                job["clips"].append({"index": index, "start_seconds": start, "end_seconds": end, "analysis": analysis})
                job.update(completed_chunks=len(job["clips"]), processed_seconds=end,
                           coverage_ratio=min(1.0, end / duration))
                _save(directory, job)
            from research_memory import remember_clip
            remember_clip(directory.name,index,analysis,job["filename"])
        if cancel.is_set():
            _cancelled()
        terminal_status, terminal_error = "completed", None
    except Exception as error:
        terminal_status = "cancelled" if cancel.is_set() else "failed"
        terminal_error = (str(error) if isinstance(error, (LectureError, lecture_provider.LectureProviderError))
                          else "课堂解析未完成。已保留成功片段，请检查视频模型配置或网络后重试。")
        inherited_cleanup_failure = bool(getattr(error, "cleanup_failed", False))
    finally:
        # Keep the visible job active until remote cleanup is settled. Otherwise
        # the UI could stop polling a completed report and miss a late warning.
        with _lock:
            try:
                job = _read(directory)
                job.update(status="cleaning_remote", error=terminal_error)
                _save(directory, job)
            except LectureError:
                pass
        cleanup_failed = inherited_cleanup_failure
        if remote is not None:
            try:
                lecture_provider.delete_remote(remote.name, api_key)
            except Exception:
                cleanup_failed = True
        # The key is not stored on the job, future, status result or report.
        api_key = ""
        with _lock:
            try:
                job = _read(directory)
                job.update(status=terminal_status, error=terminal_error,
                           cleanup_failed=bool(job["cleanup_failed"] or cleanup_failed))
                _save(directory, job)
            except LectureError:
                pass
            _active.pop(str(directory), None)


def start_analysis(job_id, *, api_key, model, chunk_seconds=300, remote_upload_confirmed=False):
    if (not isinstance(api_key, str) or not api_key.strip() or len(api_key) > 4096
            or any(ord(char) < 33 or ord(char) > 126 for char in api_key)):
        raise LectureError("请填写有效的视频模型 API 密钥。", 422)
    if not isinstance(model, str) or not MODEL_PATTERN.fullmatch(model):
        raise LectureError("请填写有效的 Gemini 视频模型名称。", 422)
    if type(chunk_seconds) is not int or chunk_seconds not in {180, 300, 600}:
        raise LectureError("请选择 3、5 或 10 分钟的解析区间。", 422)
    if remote_upload_confirmed is not True:
        raise LectureError("请确认将此视频上传到所选视频模型平台并开始解析。", 422)
    directory = job_directory(job_id)
    global _executor
    with _lock:
        job = _read(directory)
        if str(directory) in _active or str(directory) in _uploads or job["status"] in ACTIVE:
            raise LectureError("此视频正在解析，请先停止并等待当前请求结束。", 409)
        if job["status"] == "completed":
            raise LectureError("此视频已完成解析，可直接查看或导出结果。", 409)
        config = {"model": model, "chunk_seconds": chunk_seconds}
        if job["analysis_config"] is not None and job["analysis_config"] != config:
            raise LectureError("继续解析须保持原模型和区间长度；需要更改时请重新上传。", 409)
        video_path(job_id)
        cancel = threading.Event()
        _active[str(directory)] = cancel
        job.update(status="queued", model=model, chunk_seconds=chunk_seconds,
                   analysis_config=config, error=None)
        try:
            _save(directory, job)
            if _executor is None:
                _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mathpath-classroom")
            _executor.submit(_run, directory, api_key, model, chunk_seconds, cancel)
        except Exception:
            _active.pop(str(directory), None)
            job.update(status="failed", error="无法启动课堂解析任务，请稍后重试。")
            _save(directory, job)
            raise LectureError("无法启动课堂解析任务，请稍后重试。", 503) from None
        return get_job(directory.name)


def cancel_analysis(job_id):
    directory = job_directory(job_id)
    with _lock:
        job = _read(directory)
        cancel = _active.get(str(directory))
        if cancel is not None:
            cancel.set()
            job["error"] = "已请求停止；正在等待当前请求结束，后续片段不会继续发送。"
            _save(directory, job)
        return get_job(directory.name)


def delete_job(job_id):
    directory = job_directory(job_id)
    with _lock:
        _read(directory)
        if str(directory) in _active or str(directory) in _uploads:
            raise LectureError("解析仍在结束处理中，请稍后再删除。", 409)
        root = data_root().resolve()
        resolved = directory.resolve()
        if directory.is_symlink() or resolved.parent != root or not ID_PATTERN.fullmatch(resolved.name):
            raise LectureError("课堂记录路径无效。", 404)
        try:
            shutil.rmtree(resolved)
        except OSError:
            raise _storage_error() from None
    return {"deleted": True}


def export_job(job_id, format="json"):
    job = get_job(job_id)
    import lecture_tutor
    tutoring = lecture_tutor.sessions(job_id)
    if format == "json":
        return _json_bytes({"format": "mathpath_classroom_report", "version": 1, "job": job, "tutoring": tutoring})
    if format != "markdown":
        raise LectureError("请选择 JSON 或 Markdown 导出。", 422)
    lines = ["# " + job["filename"], "", "来源：视频模型候选解析，数学内容仍需核对。",
             f"状态：{job['status']}；已处理 {job['processed_seconds']:g} 秒 / {job['duration_seconds'] or 0:g} 秒。",
             "时间区间处理比例不代表全部细节已识别或数学正确。", ""]
    if job["error"]:
        lines.extend(["未完成说明：" + job["error"], ""])
    if job["cleanup_failed"]:
        lines.extend(["视频平台文件清理未确认，请在视频平台检查该次上传。", ""])
    for clip in job["clips"]:
        analysis = clip["analysis"]
        lines.extend([f"## {clip['start_seconds']:g}–{clip['end_seconds']:g} 秒：{analysis['title']}", "", analysis["overview"], ""])
        for item in analysis["items"]:
            lines.extend([f"### {item['start_seconds']:g}–{item['end_seconds']:g} 秒：{item['title']}",
                          "", "视频内容：" + item["source_summary"], "", "解析：" + item["explanation"], ""])
            for field, heading in [("formulas", "公式"), ("steps", "推导步骤"), ("uncertainties", "待核对")]:
                if item[field]:
                    lines.extend([heading + "：", *["- " + value for value in item[field]], ""])
        if analysis["learning_goals"]:
            lines.extend(["### 学习目标", "", *["- " + value for value in analysis["learning_goals"]], ""])
        for practice in analysis["practice"]:
            lines.extend(["### 练习（" + ("视频原题" if practice["origin"] == "from_video" else "补充练习") + "）", "",
                          practice["question"], "", "提示：" + practice["hint"], "", "参考：" + practice["answer"], ""])
        for field, heading in [("coverage_notes", "覆盖说明"), ("uncertainties", "待核对")]:
            if analysis[field]:
                lines.extend([heading + "：", *["- " + value for value in analysis[field]], ""])
    if tutoring:
        lines.append(lecture_tutor.export_markdown(tutoring))
    return "\n".join(lines).encode("utf-8")


def shutdown_workers():
    global _executor
    with _lock:
        for cancel in _active.values():
            cancel.set()
        if _executor is not None:
            # Queued workers must run their cancellation cleanup so their active
            # registry entries do not survive application/test lifespan changes.
            _executor.shutdown(wait=False, cancel_futures=False)
            _executor = None
