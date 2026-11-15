"""Full-video ingestion from the paired extension. URLs and browser cookies never enter this API."""
import hashlib
import json
import math
import threading
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from chatgpt_login import atomic_write, protect_bytes
from lecture_routes import tutor_payload, result
import lecture_provider as provider
import lecture_store as store

router = APIRouter()
lock = threading.RLock()
imports = {}
MAX_CHUNK = 256 * 1024


def root(): return store.data_root().parent / 'video-connection'


class VideoSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    api_key: str = Field(min_length=1, max_length=4096, repr=False)
    model: str = Field(default=provider.DEFAULT_VIDEO_MODEL, pattern=r'^gemini-[a-z0-9][a-z0-9._-]{0,119}$')
    chunk_seconds: int = 300
    remote_upload_confirmed: bool = False


def settings():
    path = root() / 'public.json'
    default = {'configured':False,'model':provider.DEFAULT_VIDEO_MODEL,'chunk_seconds':300}
    if not path.exists(): return default
    try:
        if path.is_symlink() or path.stat().st_size > 4096: raise ValueError
        data = json.loads(path.read_bytes())
        if set(data) != {'configured','model','chunk_seconds','revision'} or data['configured'] is not True: raise ValueError
        if not provider._MODEL.fullmatch(data['model']) or data['chunk_seconds'] not in {180,300,600}: raise ValueError
        return data
    except Exception: raise store.LectureError('视频模型连接无法读取，请重新保存设置。',503) from None


def save_settings(body):
    if not body.remote_upload_confirmed: raise store.LectureError('请先确认：点击生成解析时，将整段视频交给所选视频模型处理。',422)
    if body.chunk_seconds not in {180,300,600}: raise store.LectureError('请选择 3、5 或 10 分钟的分段长度。',422)
    try: provider._key(body.api_key)
    except provider.LectureProviderError: raise store.LectureError('请填写有效的视频模型 API 密钥。',422) from None
    revision = str(uuid4())
    private = {'api_key':body.api_key,'revision':revision}
    public = {'configured':True,'model':body.model,'chunk_seconds':body.chunk_seconds,'revision':revision}
    atomic_write(root()/'connection.dpapi',protect_bytes(json.dumps(private).encode()))
    atomic_write(root()/'public.json',json.dumps(public).encode())
    return public


def credentials():
    config = settings()
    if not config['configured']: raise store.LectureError('首次使用请先配置视频模型。保存一次后，侧栏只需点击“生成解析”。',409)
    path = root()/'connection.dpapi'
    try:
        if path.is_symlink() or path.stat().st_size > 20000: raise ValueError
        secret = json.loads(protect_bytes(path.read_bytes(),decrypt=True))
        if secret['revision'] != config['revision']: raise ValueError
        provider._key(secret['api_key'])
        return config,secret['api_key']
    except Exception: raise store.LectureError('本机视频模型密钥无法解密，请重新保存连接。',503) from None


class ImportInput(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)
    request_id: str = Field(pattern=r'^[\da-f-]{36}$')
    source_key: str = Field(pattern=r'^[\da-f]{64}$')
    filename: str = Field(min_length=1,max_length=180)
    mime_type: str
    duration_seconds: float = Field(gt=0,le=10800)
    size_bytes: int | None = Field(default=None,gt=0,le=store.MAX_VIDEO_BYTES)


def _mapping(source_key): return root()/'bindings'/(source_key+'.json')


def binding(source_key):
    if len(source_key)!=64 or any(c not in '0123456789abcdef' for c in source_key): raise store.LectureError('视频标识无效。',422)
    path = _mapping(source_key)
    try:
        if not path.exists(): return {'lecture':None}
        if path.is_symlink() or path.stat().st_size>1024: raise ValueError
        return {'lecture':store.get_job(json.loads(path.read_bytes())['lecture_id'],summary=True)}
    except store.LectureError as e:
        if e.status_code==404: return {'lecture':None}
        raise
    except Exception: raise store.LectureError('当前视频的本地关联无法读取。',503) from None


def start_import(body):
    # Configuration is checked before downloading hundreds of MB from the page.
    config = settings()
    if not config['configured']: raise store.LectureError('首次使用请先设置视频模型，之后只需点击生成解析。',409)
    mime = store.validate_upload(body.filename,body.mime_type,body.size_bytes,body.duration_seconds)
    with lock:
        for sid,row in list(imports.items()):
            if time.monotonic()-row['touched']>1800:
                store.abort_upload(row['directory']); del imports[sid]
            elif row['request_id']==body.request_id:
                if row['body']!=body.model_dump(): raise store.LectureError('同一视频导入请求的内容发生变化。',409)
                return {'import_id':sid,'offset':row['size']}
        if len(imports)>=4: raise store.LectureError('同时导入的视频过多，请等待已有任务。',429)
        directory = store.begin_upload(body.filename,mime,body.size_bytes,body.duration_seconds)
        (directory/'video.part').touch(exist_ok=False)
        sid=str(uuid4()); imports[sid]={'directory':directory,'body':body.model_dump(),'request_id':body.request_id,
             'size':0,'digest':hashlib.sha256(),'touched':time.monotonic()}
        return {'import_id':sid,'offset':0}


def append(sid,offset,raw):
    with lock:
        row=imports.get(sid)
        if not row: raise store.LectureError('视频导入已结束或中断，请重新生成解析。',404)
        if not raw or len(raw)>MAX_CHUNK: raise store.LectureError('视频分块大小无效。',413)
        if offset<row['size']:
            with (row['directory']/'video.part').open('rb') as f: f.seek(offset); same=f.read(len(raw))==raw
            if same: return {'offset':row['size']}
        if offset!=row['size']: raise store.LectureError('视频分块顺序不一致，已保留已接收内容。',409)
        limit=row['body']['size_bytes'] or store.MAX_VIDEO_BYTES
        if row['size']+len(raw)>min(limit,store.MAX_VIDEO_BYTES): raise store.LectureError('视频大小超出允许范围。',413)
        with (row['directory']/'video.part').open('ab') as f:f.write(raw)
        row['digest'].update(raw);row['size']+=len(raw);row['touched']=time.monotonic()
        return {'offset':row['size']}


def finish(sid):
    with lock:
        row=imports.get(sid)
        if not row: raise store.LectureError('视频导入已结束，请刷新解析状态。',404)
        b=row['body']
        if not row['size'] or (b['size_bytes'] is not None and row['size']!=b['size_bytes']): raise store.LectureError('原视频尚未读取完整，请重试。',422)
        digest=row['digest'].hexdigest()
        # Re-reading the same source must not rebill an already parsed video.
        for old in store.list_jobs():
            if old.get('video_sha256')==digest and old.get('video_available'):
                store.abort_upload(row['directory']);del imports[sid]
                atomic_write(_mapping(b['source_key']),json.dumps({'lecture_id':old['id']}).encode())
                return old
        job=store.finish_upload(row['directory'],b['filename'],b['mime_type'],row['size'],digest,b['duration_seconds'])
        atomic_write(_mapping(b['source_key']),json.dumps({'lecture_id':job['id']}).encode())
        del imports[sid];return job


def cancel(sid):
    with lock:
        row=imports.pop(sid,None)
        if row:store.abort_upload(row['directory'])
    return {'cancelled':True}


def analyze(job_id):
    job=store.get_job(job_id)
    if job['status']=='completed' or job['status'] in store.ACTIVE:return job
    config,key=credentials()
    return store.start_analysis(job_id,api_key=key,model=config['model'],chunk_seconds=config['chunk_seconds'],remote_upload_confirmed=True)


async def call(fn,*args):
    try:return await run_in_threadpool(fn,*args)
    except store.LectureError as e:raise HTTPException(status_code=e.status_code,detail=str(e)) from None
    except Exception:raise HTTPException(status_code=503,detail='整课解析暂时未完成，请检查本机存储或视频模型设置后重试。') from None


@router.get('/settings/video')
@router.get('/canvas-bridge/video-settings')
def get_settings():return result(settings)


@router.post('/settings/video')
async def put_settings(request:Request):return await call(save_settings,await tutor_payload(request,VideoSettings))


@router.get('/canvas-bridge/video-bindings/{source_key}')
def get_binding(source_key:str):return result(binding,source_key)


@router.post('/canvas-bridge/video-imports')
async def begin(request:Request):return await call(start_import,await tutor_payload(request,ImportInput))


@router.post('/canvas-bridge/video-imports/{sid}/chunks')
async def upload_chunk(sid:str,request:Request,offset:int=0):
    if offset<0:raise HTTPException(status_code=422,detail='视频分块位置无效。')
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>MAX_CHUNK:raise HTTPException(status_code=413,detail='视频分块过大。')
    return await call(append,sid,offset,bytes(raw))


@router.post('/canvas-bridge/video-imports/{sid}/finish')
async def finish_import(sid:str):return await call(finish,sid)


@router.post('/canvas-bridge/video-imports/{sid}/cancel')
async def cancel_import(sid:str):return await call(cancel,sid)


@router.get('/canvas-bridge/video-jobs/{job_id}')
def video_job(job_id:str):return result(store.get_job,job_id,summary=True)


@router.post('/canvas-bridge/video-jobs/{job_id}/analyze')
async def analyze_video(job_id:str):return await call(analyze,job_id)


@router.post('/canvas-bridge/video-jobs/{job_id}/cancel')
async def cancel_video(job_id:str):return await call(store.cancel_analysis,job_id)
