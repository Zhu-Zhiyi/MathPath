"""Local research workspaces and named Markdown theorem records."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
import threading
import time
from urllib.parse import urlencode, urlsplit
import urllib.request
import xml.etree.ElementTree as ET
from uuid import uuid4
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

import lecture_store as store
from chatgpt_login import atomic_write
from lecture_routes import tutor_payload
from memory_models import MemoryCandidate

router = APIRouter(prefix="/research", tags=["research"])
_lock = threading.RLock()
_paper_lock = threading.Lock()
_paper_time = 0.0
_paper_cache = {}


def root():
    return store.data_root().parent / "research-memory"


def now():
    return datetime.now(timezone.utc).isoformat()


class WorkspaceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=180)
    intent: str = Field(pattern=r"^(question|explore|study)$")
    question: str = Field(default="", max_length=4000)
    background: str = Field(default="", max_length=3000)
    search_terms: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def valid(self):
        if not self.title.strip() or (self.intent == "question" and not self.question.strip()):
            raise ValueError("请填写研究问题")
        return self


class TheoremInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=180)
    aliases: list[str] = Field(default_factory=list, max_length=10)
    category: str = Field(pattern=r"^(common|nonstandard)$")
    statement: str = Field(min_length=1, max_length=16000)
    assumptions: list[str] = Field(default_factory=list, max_length=24)
    intuition: str = Field(default="", max_length=6000)
    proof_idea: str = Field(default="", max_length=12000)
    source: str = Field(min_length=1, max_length=4000)
    source_url: str = Field(default="", max_length=1000)
    uncertainties: list[str] = Field(default_factory=list, max_length=16)
    statement_complete: bool = False
    verified_by_user: bool = False
    workspace_id: str | None = None
    record_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def valid(self):
        if not all(s.strip() for s in (self.name, self.statement, self.source)):
            raise ValueError("名称、陈述和来源不能为空")
        if any(not isinstance(s, str) or not s.strip() or len(s) > 1600 for s in [*self.aliases, *self.assumptions, *self.uncertainties]):
            raise ValueError("定理条目过长或为空")
        if self.source_url:
            u = urlsplit(self.source_url)
            if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ValueError("来源地址只接受不带登录、查询或片段信息的 HTTPS 页面")
        if self.verified_by_user and (not self.statement_complete or self.uncertainties):
            raise ValueError("有缺项或疑问时不能标为已核对")
        return self


def _path(kind, record_id):
    if not isinstance(record_id, str) or not store.ID_PATTERN.fullmatch(record_id):
        raise store.LectureError("科研记录不存在。", 404)
    path = root() / kind / (record_id + ".json")
    if path.is_symlink():
        raise store.LectureError("科研记录路径无效。", 409)
    return path


def _read(kind, record_id):
    path = _path(kind, record_id)
    try:
        if path.stat().st_size > 512000:
            raise ValueError
        data = json.loads(path.read_bytes())
        if not isinstance(data, dict) or data.get("id") != record_id:
            raise ValueError
        return data
    except FileNotFoundError:
        raise store.LectureError("科研记录不存在。", 404) from None
    except (ValueError, OSError):
        raise store.LectureError("科研记录无法读取，请检查文件。", 503) from None


def _list(kind):
    directory = root() / kind
    if not directory.exists(): return []
    records = []
    for path in directory.glob("*.json"):
        if store.ID_PATTERN.fullmatch(path.stem): records.append(_read(kind, path.stem))
    return sorted(records, key=lambda value: value["updated_at"], reverse=True)


def workspaces():
    with _lock: return _list("workspaces")


def workspace(record_id):
    with _lock: return _read("workspaces", record_id)


def save_workspace(body):
    with _lock:
        if len(_list("workspaces")) >= 200: raise store.LectureError("研究工作区已达到 200 个。", 409)
        record = {"id": str(uuid4()), "updated_at": now(), **body.model_dump()}
        atomic_write(_path("workspaces", record["id"]), json.dumps(record, ensure_ascii=False).encode())
        return record


def theorem_markdown(record):
    status = "已由用户对照来源核对" if record["verified_by_user"] else "候选，仍需核对"
    if not record["statement_complete"]: status += "；陈述待补全，不能直接引用"
    lines = ["---", "id: " + record["id"], "name: " + json.dumps(record["name"], ensure_ascii=False),
             "status: " + json.dumps(status, ensure_ascii=False), "category: " + record["category"],
             "revision: " + str(record["revision"]), "workspace_id: " + str(record["workspace_id"] or "null"),
             "updated_at: " + record["updated_at"], "---", "", "# " + record["name"], "", status, "",
             "别名：" + "；".join(record["aliases"]), "", "## 采用的版本与完整陈述", "", record["statement"], "",
             "## 假设、对象与适用范围", "", *["- " + s for s in record["assumptions"]], "",
             "## 直观", "", record["intuition"], "", "## 证明线索", "", record["proof_idea"], "",
             "## 来源", "", record["source"], record["source_url"], "", "## 尚需核对", "", *["- " + s for s in record["uncertainties"]], ""]
    return "\n".join(lines)


def theorem_path(record):
    # The display name never controls a directory; UUID disambiguates homonyms.
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", record["name"]).strip(" .")[:65] or "定理"
    return root() / "theorems" / f"{safe}__{record['id'][:8]}.md"


def theorems(query="", workspace_id=None, verified_only=False):
    with _lock:
        records = _list("theorems")
    terms = query.casefold().strip().split()
    return [r for r in records if (not workspace_id or r["workspace_id"] == workspace_id)
            and (not verified_only or r["verified_by_user"])
            and all(t in (r["name"] + " " + " ".join(r["aliases"]) + " " + r["statement"]).casefold() for t in terms)]


def save_theorem(body, *, origin="manual", source_key=None):
    if body.workspace_id: workspace(body.workspace_id)
    value = body.model_dump(exclude={"record_id", "expected_revision"})
    digest = hashlib.sha256(json.dumps({k: value[k] for k in ("name", "statement", "assumptions", "workspace_id")}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with _lock:
        records = _list("theorems")
        existing = _read("theorems", body.record_id) if body.record_id else None
        if existing:
            origin = existing.get("origin", "manual")
            source_key = existing.get("source_key")
        if existing and body.expected_revision != existing["revision"]:
            raise store.LectureError("这个定理已被其他窗口修改，请重新载入再保存。", 409)
        duplicate = next((r for r in records if r["digest"] == digest and (not existing or r["id"] != existing["id"])), None)
        if duplicate: return duplicate
        if not existing and len(records) >= 3000: raise store.LectureError("定理记录已达到 3000 条，请先整理。", 409)
        record = {"id": existing["id"] if existing else str(uuid4()), "revision": existing["revision"] + 1 if existing else 1,
                  "updated_at": now(), "digest": digest, "origin": origin, "source_key": source_key, **value}
        path = theorem_path(record)
        if existing:
            previous = theorem_path(existing)
            archive = root() / "versions" / existing["id"] / f"r{existing['revision']}.md"
            atomic_write(archive, theorem_markdown(existing).encode("utf-8"))
        # Markdown is written first; JSON visibility follows only after success.
        atomic_write(path, theorem_markdown(record).encode("utf-8"))
        atomic_write(_path("theorems", record["id"]), json.dumps(record, ensure_ascii=False).encode("utf-8"))
        if existing and previous != path and previous.is_file() and not previous.is_symlink() and previous.resolve().is_relative_to(root().resolve()):
            previous.unlink()
        return record


def remember(items, *, source_key, source, workspace_id=None):
    """AI owns capture/dedup/versioning; its output never certifies itself."""
    saved=[]
    if not items:return {"status":"skipped","ids":[],"message":"这段未识别出需要单独存档的定理。"}
    try:
        with _lock:
            records=theorems()
            for raw in items:
                data=dict(raw)
                data.update(source=source,workspace_id=workspace_id,verified_by_user=False)
                body=TheoremInput.model_validate(data)
                key=hashlib.sha256((source_key+"|"+body.name.casefold().strip()+"|"+str(workspace_id)).encode()).hexdigest()
                old=next((r for r in records if r.get("source_key")==key and r.get("origin")=="ai" and not r["verified_by_user"]),None)
                if old:
                    comparable=body.model_dump(exclude={"record_id","expected_revision"})
                    if all(old.get(k)==v for k,v in comparable.items()): saved.append(old["id"]);continue
                    body=body.model_copy(update={"record_id":old["id"],"expected_revision":old["revision"]})
                result=save_theorem(body,origin="ai",source_key=key)
                saved.append(result["id"])
        return {"status":"saved" if saved else "skipped","ids":saved,"message":f"AI 已自动整理 {len(saved)} 条定理记忆；均保留核对状态。" if saved else "这段未识别出需要单独存档的定理。"}
    except Exception:
        return {"status":"failed","ids":saved,"message":"内容已生成，但自动记忆未完全保存；请检查本机存储后重试。"}


def remember_clip(job_id, index, analysis, filename):
    items=[{"name":item["title"],"category":"nonstandard","statement":item["source_summary"],
            "assumptions":[],"intuition":item["explanation"],"proof_idea":"\n".join(item["steps"]),
            "uncertainties":["课堂自动识别结果，完整条件与版本仍需核对。",*item["uncertainties"]][:16],"statement_complete":False}
           for item in analysis["items"] if item["kind"]=="theorem" and item["source_summary"].strip()]
    return remember(items,source_key=f"lecture:{job_id}:clip:{index}",source=f"{filename}，片段 {index+1}；课堂自动解析，需回看来源核对。")


def recall_candidates(workspace_id, query=""):
    rows=[r for r in theorems() if r["workspace_id"]==workspace_id and not r["verified_by_user"]]
    query=query.casefold()
    def tokens(text):
        groups=re.findall(r"[\u4e00-\u9fff]+|[a-z]{3,}",text.casefold())
        return {t for g in groups for t in ([g] if g.isascii() else [g[i:i+2] for i in range(len(g)-1)]) if t not in {"定理","证明","问题","理解","数学","theorem","proof","lemma"}}
    terms=tokens(query)
    def score(r):return (100 if r["name"].casefold() in query else 0)+len(terms&tokens(r["name"]+" "+" ".join(r["aliases"])+" "+r["statement"][:1500]))
    rows=[r for r in rows if query.strip() and score(r)>0]
    rows.sort(key=score,reverse=True)
    output=[];budget=14000
    for r in rows[:4]:
        item={k:r[k] for k in ("id","name","statement","assumptions","source","uncertainties","statement_complete")}
        item.update(status="unverified_memory",review_required=True)
        size=len(json.dumps(item,ensure_ascii=False))
        if size<=budget:output.append(item);budget-=size
    return output


def _fetch_feed(url):
    class FixedRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            target = urlsplit(newurl)
            if target.scheme != "https" or target.hostname not in {"export.arxiv.org", "arxiv.org"} or target.username or target.password:
                raise ValueError("Unexpected redirect")
            return super().redirect_request(request, fp, code, msg, headers, newurl)
    request = urllib.request.Request(url, headers={"User-Agent": "MathPath/0.1 classroom-research"})
    with urllib.request.build_opener(FixedRedirect()).open(request, timeout=25) as response:
        return response.read(1000001)


def recent_papers(terms):
    global _paper_time
    if not isinstance(terms, str) or not terms.strip() or len(terms) > 200:
        raise store.LectureError("请填写公开的文献检索关键词，建议使用英文。", 422)
    key = terms.strip()
    with _paper_lock:
        cached = _paper_cache.get(key)
        if cached and time.monotonic() - cached[0] < 3600: return cached[1]
        if time.monotonic() - _paper_time < 3:
            raise store.LectureError("文献检索过于频繁，请等几秒再试。", 429)
        _paper_time = time.monotonic()
        query = " AND ".join('all:"' + token.replace('"', '') + '"' for token in key.split()[:12])
        url = "https://export.arxiv.org/api/query?" + urlencode({"search_query": query, "max_results": 8, "sortBy": "submittedDate", "sortOrder": "descending"})
        try:
            raw = _fetch_feed(url)
            if len(raw) > 1000000 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper(): raise ValueError
            feed = ET.fromstring(raw)
            ns = {"a": "http://www.w3.org/2005/Atom"}
            today = datetime.now(timezone.utc)
            papers = []
            for entry in feed.findall("a:entry", ns):
                source_id = entry.findtext("a:id", "", ns).rsplit("/abs/", 1)[-1]
                if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?", source_id): continue
                published = entry.findtext("a:published", "", ns)
                date = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if date.tzinfo is None or not today - timedelta(days=730) <= date <= today + timedelta(days=1): continue
                papers.append({"id": source_id, "title": " ".join(entry.findtext("a:title", "", ns).split())[:600],
                               "published": published, "url": "https://arxiv.org/abs/" + source_id,
                               "abstract": " ".join(entry.findtext("a:summary", "", ns).split())[:5000]})
            value = {"retrieved_at": now(), "query": key, "window_days": 730, "papers": papers}
            if len(_paper_cache) >= 100: _paper_cache.clear()
            _paper_cache[key] = (time.monotonic(), value)
            return value
        except Exception:
            raise store.LectureError("近期文献检索未完成；没有用模型编造论文替代结果。请稍后重试。", 502) from None


def wrap(operation, *args):
    try: return operation(*args)
    except store.LectureError as error: raise HTTPException(status_code=error.status_code, detail=str(error)) from None


@router.get("/workspaces")
def list_workspaces(): return wrap(workspaces)


@router.post("/workspaces")
async def create_workspace(request: Request):
    return wrap(save_workspace, await tutor_payload(request, WorkspaceInput))


@router.get("/theorems")
def list_theorems(q: str = Query(default="", max_length=200), workspace_id: str | None = None):
    return wrap(theorems, q, workspace_id)


@router.post("/theorems")
async def create_theorem(request: Request):
    return wrap(save_theorem, await tutor_payload(request, TheoremInput))


@router.get("/theorems/{theorem_id}/markdown")
def download_theorem(theorem_id: str):
    value = wrap(_read, "theorems", theorem_id)
    path = theorem_path(value)
    if not path.is_file() or path.is_symlink(): raise HTTPException(status_code=503, detail="定理 Markdown 文件缺失或路径无效，请检查本机记忆文件夹。")
    return FileResponse(path, media_type="text/markdown", filename=path.name)
