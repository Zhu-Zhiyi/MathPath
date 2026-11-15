"""Collect a verified desktop release and extension into a private-data-free share folder."""
from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile

from build import FORBIDDEN, PROJECT, VERSION, release_allowlist, sha256, verify_sources


def load(path): return json.loads(path.read_text(encoding="utf-8"))


def stream_hash(stream):
    value=hashlib.sha256()
    for part in iter(lambda:stream.read(1024*1024),b""): value.update(part)
    return value.hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--release-dir",type=Path,required=True)
    parser.add_argument("--notebook",type=Path,required=True)
    args=parser.parse_args()
    release_dir=args.release_dir.resolve()
    stem=f"MathPath-desktop-{VERSION}-windows-x64"
    portable=release_dir/stem
    manifest=load(portable/"manifest.json")
    files=release_allowlist(manifest,portable)
    verify_sources([PROJECT/e["path"] for e in manifest["source_files"]],manifest["source_files"])
    assert manifest["version"]==VERSION and manifest["excluded_data_absent"] and not manifest["credentials_bundled"]
    assert sha256(portable/manifest["executable"])==manifest["executable_sha256"]
    setup_stem=f"MathPath-setup-{VERSION}-windows-x64"
    setup=release_dir/(setup_stem+".exe")
    setup_manifest=load(release_dir/(setup_stem+"-manifest.json"))
    assert sha256(setup)==setup_manifest["setup_sha256"] and setup_manifest["payload_allowlist_verified"]
    assert setup_manifest["payload_sha256"]==manifest["executable_sha256"]
    for report in (load(portable/"self-test.json"),load(portable/"window-test.json"),setup_manifest["self_test"]["installed_application_self_test"]):
        assert report["status"]=="ok" and report["version"]==VERSION and report["server_stopped"]
        assert all(report[k]==0 for k in ("model_requests","credential_reads","chatgpt_login_attempts","external_auth_requests"))
        assert all(report[k] for k in ("classroom_resources","research_resources","theorem_markdown_roundtrip","extension_pairing_roundtrip","notes_resources","notes_opt_in"))

    notebook=args.notebook.resolve()
    if not notebook.is_dir(): raise RuntimeError("Notebook directory does not exist")
    name=f"{datetime.now():%Y-%m-%d}_MathPath-v{VERSION}-Windows"
    destination=notebook/name
    archive=notebook/(name+".zip")
    if destination.exists() or archive.exists(): raise RuntimeError("Destination already exists; preserve it and choose a new name")
    if not destination.resolve().is_relative_to(notebook): raise RuntimeError("Unexpected destination")
    destination.mkdir()
    included=set()

    def safe_relative(relative):
        p=PurePosixPath(relative)
        if p.is_absolute() or str(p)!=relative or ".." in p.parts or ":" in relative or "\\" in relative or FORBIDDEN.search(relative): raise RuntimeError("Unsafe public bundle path")
        return p

    def copy_file(original,relative):
        p=safe_relative(relative)
        if not original.is_file() or original.is_symlink(): raise RuntimeError("Missing or external source")
        target=destination/str(p);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(original,target)
        if sha256(original)!=sha256(target):raise RuntimeError("Copy checksum mismatch")
        included.add(str(p))

    def text_file(relative,value):
        p=safe_relative(relative);target=destination/str(p);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(value,encoding="utf-8-sig" if p.suffix==".txt" else "utf-8");included.add(str(p))

    copy_file(portable/manifest["executable"],manifest["executable"])
    copy_file(setup,setup.name)
    copy_file(portable/"README-中文.txt","说明/桌面版使用说明.txt")
    for relative in files:
        if relative.startswith("licenses/"):copy_file(portable/relative,relative)
    extension=PROJECT/"browser-extension"/"mathpath-canvas"
    extension_check=load(PROJECT/"outputs"/"canvas-companion"/"package-check.json")
    for relative in extension_check["files"]:
        safe_relative(relative)
        copy_file(extension/relative,"Canvas伴学扩展/"+relative)
    for source,target in [(portable/"manifest.json","桌面版构建清单.json"),(portable/"self-test.json","桌面版离线自检.json"),
                          (portable/"window-test.json","桌面窗口自检.json"),(release_dir/(setup_stem+"-manifest.json"),"安装包构建清单.json"),
                          (release_dir/(setup_stem+"-self-test.json"),"安装及升级自检.json"),
                          (PROJECT/"outputs"/"canvas-companion"/"package-check.json","扩展打包检查.json")]:
        copy_file(source,"验证报告/"+target)
    for filename,target in [("docs/canvas-companion.md","Canvas伴学与科研记忆.md"),("docs/classroom.md","课堂解析.md"),("docs/notes-and-memory.md","自动记忆与ABC笔记.md")]:
        copy_file(PROJECT/filename,"说明/"+target)
    playback_check=load(release_dir/"playback-notes-check.json")
    if playback_check["status"]!="ok" or not playback_check["real_media_clock_updates_notes"] or not playback_check["export_remains_opt_in"]:
        raise RuntimeError("Playback sidebar verification is incomplete")
    copy_file(release_dir/"playback-notes-check.json","验证报告/视频右栏笔记检查.json")

    # Snapshot only public, explicitly approved source paths, never the project tree.
    sources={e["path"] for e in manifest["source_files"]}
    sources.update({"README.md",".gitignore",".gitattributes","requirements.txt","desktop-requirements.txt","launch.py","start.cmd",
                    "packaging/build.py","packaging/build_setup.py","packaging/build_companion.py","packaging/collect_notebook_bundle.py","packaging/installer.py",
                    "packaging/licenses/proxy_tools-LICENSE.txt","docs/canvas-companion.md","docs/classroom.md","docs/notes-and-memory.md",
                    "docs/images/rank-nullity.png","docs/images/epsilon-delta.png","tests/run_offline.py"})
    sources.update("browser-extension/mathpath-canvas/"+s for s in extension_check["files"])
    sources.update(p.relative_to(PROJECT).as_posix() for pattern in ("*.py","*.cjs") for p in (PROJECT/"tests").glob(pattern))
    source_zip=destination/f"MathPath-v{VERSION}-源码.zip"
    with zipfile.ZipFile(source_zip,"w",zipfile.ZIP_DEFLATED) as zipped:
        for relative in sorted(sources):
            # Unlike runtime payloads, source archives deliberately contain packaging/ and tests/.
            p=PurePosixPath(relative)
            if p.is_absolute() or ".." in p.parts or "\\" in relative or ":" in relative or set(p.parts)&{".mathpath",".venv","work","outputs",".git"}:raise RuntimeError("Private path reached source snapshot")
            original=PROJECT/relative
            if original.is_symlink() or not original.resolve().is_relative_to(PROJECT):raise RuntimeError("External source snapshot path")
            zipped.write(original,"MathPath/"+relative)
    with zipfile.ZipFile(source_zip) as zipped:
        assert set(zipped.namelist())=={"MathPath/"+r for r in sources} and zipped.testzip() is None
    included.add(source_zip.name)
    text_file("先看这里.txt",f"""MathPath v{VERSION} Windows 预览版 · {datetime.now():%Y-%m-%d}

直接运行：完整解压本文件夹，双击 {manifest['executable']}。
需要安装到桌面：双击 {setup.name}，按提示安装到当前 Windows 用户。
两种运行方式任选一种；无需安装 Python。Windows 10/11 64 位，需有 WebView2。
本包未作 Windows 代码签名。不要在 ZIP 压缩包内部直接启动 EXE。

打开课堂视频并阅读：
主界面进入“课堂解析”，从“我的课堂”打开已有解析的视频。
右侧直接显示笔记，随播放进度切换；可选 Type A/B/C，取消“跟随播放”可固定阅读。
点击“问问这一段”提问；使用“伴学全屏”同时保留视频与笔记。
阅读已有笔记不调用模型；点击“保存本段到本地…”后，另行勾选并设置目录才生成文件。

Canvas 伴学扩展：
1. Chrome 打开 chrome://extensions 或 Edge 打开 edge://extensions。
2. 开启开发者模式，点击“加载已解压的扩展程序”，选择本文件夹中的“Canvas伴学扩展”。
3. 主程序保持运行，菜单“Canvas 伴学设置（在浏览器打开）”打开本机设置页。
4. 在这个浏览器的扩展图标中填写页面地址栏里的 http://127.0.0.1:端口，点击连接，再在本机页面允许连接。
5. 刷新交大 Canvas / 课堂实录，关联同一节已解析课堂、校准时间。全屏用侧栏的“伴学全屏”。
真实 Canvas 播放器兼容性和全屏仍需现场检查；本包没有宣称已经通过真实课堂验收。

科研入口：主界面“Canvas 伴学 / 科研记忆”。先说明研究问题，或选学习后探索；
AI 自动整理定理记忆，无需逐条保存；候选与已核对分开，旧版保留。
可勾选生成 Type A/B/C 笔记并选择保存目录。A 结论在前、证明附录双链；B 问题与答案；C 按讲授顺序。
按日期和课程分类，C 放“Type C 讲课笔记”。不勾选本地保存就不调用导出模型或创建笔记文件，勾选后按当前模型计费。
Markdown 与 TeX 随笔记保存，PDF 需要本机 TeX Live / XeLaTeX；未安装时保留源文件。
课后可查近两年文献，模型建议是候选，仍需全文阅读、查新和数学核对。
常见定理记录具体版本和条件，非标准定理保留完整陈述；Markdown 旧版会保留。

账号与数据：本包没有附带任何人的账号、API 密钥、回放视频、历史、定理或研究问题。
内置样例可离线使用。生成新内容前，请在“模型 / API 设置”填写你自己的连接。
默认预填交大 DeepSeek 平台，使用者需要自己的可用平台账号与密钥；没有共享密钥。
课堂视频解析需另填自己的多模态模型连接，扩展不会自动读取或上传回放视频。
各项模型请求只有在相应按钮确认时发送，并按平台规则计费；本次打包自检未调用真实模型。
个人数据在 %LOCALAPPDATA%\\MathPath；研究与定理在 .mathpath\\research-memory，课堂在 .mathpath\\lectures。
原“完整备份学习库”不包含这两个新文件夹，请单独保管；个人数据不要加进对外分享包。

说明目录有详细教程；验证报告目录保存程序与安装包的检查结果。
SHA256SUMS.txt 可检查文件完整性；“MathPath-v{VERSION}-源码.zip”是本次公开源码快照，供开发与备份。
将旁边的 {name}.zip 发给其他人即可；对方完整解压后按以上步骤运行。
""")
    summary={"version":VERSION,"result":"passed","desktop_executable_sha256":manifest["executable_sha256"],"setup_sha256":setup_manifest["setup_sha256"],
             "extension_version":extension_check["extension_version"],"public_files_only":True,"source_snapshot_files":len(sources),"real_model_calls":0,
             "desktop_self_test":"passed","desktop_window_test":"passed","installer_upgrade_test":"passed",
             "real_canvas_fullscreen_acceptance":"pending field check","personal_credentials_or_learning_data_included":False}
    text_file("验证报告/分享包检查.json",json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    checksum_lines=[sha256(destination/r)+"  "+r for r in sorted(included)]
    text_file("SHA256SUMS.txt","\n".join(checksum_lines)+"\n")
    actual={p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
    if actual!=included:raise RuntimeError("Unexpected file reached the share folder")
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as zipped:
        for relative in sorted(included):zipped.write(destination/relative,name+"/"+relative)
    with zipfile.ZipFile(archive) as zipped:
        assert set(zipped.namelist())=={name+"/"+r for r in included}
        for relative in included:
            with zipped.open(name+"/"+relative) as stream:
                if stream_hash(stream)!=sha256(destination/relative):raise RuntimeError("ZIP checksum mismatch")
    result={"folder":str(destination),"zip":str(archive),"zip_bytes":archive.stat().st_size,"zip_sha256":sha256(archive),"files":len(included),"all_file_hashes_verified":True,"status":"ok"}
    (release_dir/"notebook-delivery-check.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
