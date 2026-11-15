"""Pinned local recognition tools. Downloads happen only for an explicit video job."""
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import threading
import urllib.request
from urllib.parse import urlsplit
import zipfile

import lecture_store as store
from chatgpt_login import atomic_write

ASSETS = {
 'whisper': {'url':'https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip',
   'sha256':'6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb','bytes':8928640,'filename':'whisper-b5454.zip'},
 'ffmpeg': {'url':'https://files.pythonhosted.org/packages/82/0c/a1d49f3dd2688bd750b4986f8e271ad11f8e729a896070ea25f587b44da8/imageio_ffmpeg-0.8.1-py3-none-win_amd64.whl',
   'sha256':'f27ca4cb85e2d4946deedbce1a81245dfd942a2bcf94b53676fb3956aa95bf1b','bytes':38893483,'filename':'imageio-ffmpeg-0.8.1.whl'},
 'model': {'url':'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin?download=true',
   'sha256':'ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb','bytes':190085487,'filename':'ggml-small-q5_1.bin'},
}
_lock=threading.RLock()


def root(): return store.data_root().parent/'local-video'/'runtime'
def digest(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def status():
 base=root()
 ready=all((base/'downloads'/a['filename']).is_file() and (base/'downloads'/a['filename']).stat().st_size==a['bytes'] for a in ASSETS.values())
 return {'ready':ready,'download_bytes':sum(a['bytes'] for a in ASSETS.values()),'speech_model':'Whisper small multilingual q5_1','ocr':'Windows 本机文字识别'}


def check(cancel):
 if cancel.is_set():raise store.LectureError('已停止本机识别，已有片段保留。',409)


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  u=urlsplit(newurl)
  if u.scheme!='https' or u.username or u.password:raise store.LectureError('识别组件下载地址无效。',502)
  return super().redirect_request(req,fp,code,msg,headers,newurl)


def download(asset,target,cancel,progress):
 check(cancel)
 if target.is_file() and not target.is_symlink() and target.stat().st_size==asset['bytes'] and digest(target)==asset['sha256']:return
 target.parent.mkdir(parents=True,exist_ok=True)
 temporary=target.with_name(target.name+'.part')
 if temporary.is_symlink() or target.is_symlink():raise store.LectureError('本地识别组件路径无效。',503)
 if temporary.exists() and temporary.stat().st_size>asset['bytes']:temporary.unlink()
 try:
  # Bounded range requests also work through proxies that cap large downloads.
  opener=urllib.request.build_opener(HTTPSRedirect())
  size=temporary.stat().st_size if temporary.exists() else 0
  previous=-1
  while size<asset['bytes']:
   check(cancel);end=min(asset['bytes']-1,size+8*1024**2-1)
   headers={'User-Agent':'MathPath-local-recognition/0.6.4','Range':f'bytes={size}-{end}','Cache-Control':'no-cache'}
   req=urllib.request.Request(asset['url'],headers=headers)
   with opener.open(req,timeout=45) as response:
    if response.status==206:
     match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
     if not match or int(match[1])!=size or not size<=int(match[2])<=end or int(match[3])!=asset['bytes']:
      raise store.LectureError('识别组件分块下载范围无效，请稍后重试。',502)
     expected=int(match[2])+1
     mode='ab'
    elif response.status==200:
     size=0;expected=asset['bytes'];mode='wb'
    else:raise store.LectureError('识别组件下载未返回有效文件。',502)
    with temporary.open(mode) as out:
     while True:
      check(cancel);chunk=response.read(1024*1024)
      if not chunk:break
      size+=len(chunk)
      if size>expected:raise store.LectureError('识别组件下载大小异常。',502)
      out.write(chunk)
      percent=size*100//asset['bytes']
      if percent//5!=previous:previous=percent//5;progress(f"首次准备本机识别组件：{asset['filename']} · {percent}%")
    if size!=expected:raise store.LectureError('识别组件下载中断，已保留进度，再次生成即可继续下载。',503)
  if digest(temporary)!=asset['sha256']:
   temporary.unlink(missing_ok=True)
   raise store.LectureError('识别组件完整性校验未通过，请重新生成以重试下载。',502)
  temporary.replace(target)
 except store.LectureError:raise
 except Exception:raise store.LectureError('本机识别组件暂未下载完成，已保留进度，请检查网络后再次生成。无需注册视频模型账号。',503) from None


def extract(archive,destination,kind):
 destination.mkdir(parents=True,exist_ok=True);found=None;total=0
 with zipfile.ZipFile(archive) as source:
  for item in source.infolist():
   if item.is_dir():continue
   p=PurePosixPath(item.filename)
   if p.is_absolute() or '..' in p.parts or ':' in item.filename or '\\' in item.filename:raise store.LectureError('识别组件压缩包路径无效。',502)
   if kind=='whisper':
    selected=p.suffix.lower() in {'.exe','.dll','.txt','.md'}
   else:selected=(p.name.lower().endswith('.exe') and 'binaries' in p.parts) or any(t in p.name.lower() for t in ['license','copying'])
   if not selected:continue
   total+=item.file_size
   if item.file_size>256*1024**2 or total>512*1024**2:raise store.LectureError('识别组件解压大小异常。',502)
   path=destination.joinpath(*p.parts)
   if path.is_symlink() or not path.resolve().is_relative_to(destination.resolve()):raise store.LectureError('识别组件目标路径无效。',503)
   raw=source.read(item)
   if not path.is_file() or digest(path)!=hashlib.sha256(raw).hexdigest():atomic_write(path,raw)
   if kind=='whisper' and p.name=='whisper-cli.exe':found=path
   if kind=='ffmpeg' and p.name.lower().endswith('.exe'):found=path
 if not found:raise store.LectureError('识别组件缺少必要程序。',502)
 return found


def ensure(cancel,progress=lambda _:None):
 with _lock:
  if os.name!='nt':raise store.LectureError('当前本机识别方案适用于 Windows。',422)
  base=root();paths={}
  for name,a in ASSETS.items():
   target=base/'downloads'/a['filename'];download(a,target,cancel,progress);paths[name]=target
  check(cancel)
  whisper=extract(paths['whisper'],base/'whisper','whisper');ffmpeg=extract(paths['ffmpeg'],base/'ffmpeg','ffmpeg')
  atomic_write(base/'runtime.json',json.dumps({'whisper_version':'b5454','ffmpeg_wheel':'0.8.1','assets':ASSETS},ensure_ascii=False,indent=2).encode())
  return {'whisper':whisper,'ffmpeg':ffmpeg,'model':paths['model']}
