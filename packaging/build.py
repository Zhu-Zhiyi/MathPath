r"""Build an allowlisted, self-contained Windows release from the project venv.

Usage: .venv\Scripts\python.exe packaging\build.py --output-dir <directory>
No project directory is recursively passed to PyInstaller. In particular,
credentials, virtualenvs, experiments and previous outputs are never staged.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
from pathlib import Path
from pathlib import PurePosixPath
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
VERSION = "0.5.1"
MODULES = ["desktop.py", "main.py", "chatgpt_login.py", "graph_builder.py",
           "llm_client.py", "lesson_builder.py", "planner.py", "model_settings.py", "chatgpt_connection.py",
           "library_models.py", "library_store.py", "study_builder.py", "teaching_help.py", "learning_guidance.py"]
EXCLUDED = {".mathpath", ".venv", "outputs", "evals", "tests", "__pycache__", "results"}
FORBIDDEN = re.compile(r"(^|/)(\.mathpath|\.venv|evals|results|outputs|EBWebView|WebView2UserData)(/|$)|chatgpt_session\.dpapi|api_settings\.dpapi|host_id\.json|\.(sqlite3?|db)(?:[-.]|$)|(^|/)(desktop|state|workspace|progress)\.json$", re.IGNORECASE)
PUBLIC_PROXY_LICENSE = "packaging/licenses/proxy_tools-LICENSE.txt"
PUBLIC_PROXY_LICENSE_SHA256 = "a428fb8a2e762af3eb0a6edbbb88e9b42ccfee80fd9b423958bcacf9b9abbfe4"
KATEX_PROVENANCE_SHA256 = "dd0779593b0cee2078bc9a16cbbf1d9d5472fce173f0b8bb3646f6077d293c9b"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def release_allowlist(manifest: dict, release: Path) -> list[str]:
    """Require an explicit, canonical manifest; never enumerate a release tree."""
    entries = manifest.get("release_files")
    if not isinstance(entries, list) or not entries or not all(isinstance(entry, str) for entry in entries):
        raise RuntimeError("An explicit release_files allowlist is required")
    if len(set(entries)) != len(entries):
        raise RuntimeError("Duplicate release payload path")
    stem = f"MathPath-desktop-{VERSION}-windows-x64"
    required = {stem + ".exe", "README-中文.txt", "manifest.json", "self-test.json", "window-test.json"}
    if not required.issubset(entries):
        raise RuntimeError("Release payload is incomplete")
    for relative in entries:
        path = PurePosixPath(relative)
        if (path.is_absolute() or str(path) != relative or ".." in path.parts
                or "\\" in relative or ":" in relative or FORBIDDEN.search(relative)):
            raise RuntimeError("Unsafe release payload path")
        if relative not in required and not (len(path.parts) >= 2 and path.parts[0] == "licenses"):
            raise RuntimeError("Unapproved release payload file")
        original = release / relative
        if (not original.is_file() or original.is_symlink()
                or not original.resolve().is_relative_to(release.resolve())):
            raise RuntimeError("Release payload file is missing or external")
    return entries


def verify_sources(files: list[Path], source_files: list[dict]) -> None:
    expected = {entry["path"]: entry["sha256"] for entry in source_files}
    for path in files:
        relative = path.relative_to(PROJECT).as_posix()
        if sha256(path) != expected[relative]:
            raise RuntimeError("Source changed during release build; freeze resources and rebuild")


def verified_katex_files() -> set[Path]:
    directory = PROJECT / "static" / "vendor" / "katex"
    provenance_file = directory / "provenance.json"
    if sha256(provenance_file) != KATEX_PROVENANCE_SHA256:
        raise RuntimeError("KaTeX provenance differs from the verified official download")
    provenance = json.loads(provenance_file.read_text(encoding="utf-8"))
    if provenance.get("name") != "KaTeX" or provenance.get("version") != "0.19.0":
        raise RuntimeError("Unexpected KaTeX release")
    entries = provenance.get("files")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("KaTeX resources require an explicit file list")
    files = {provenance_file}
    for entry in entries:
        path = PurePosixPath(entry["path"])
        if path.is_absolute() or str(path) != entry["path"] or ".." in path.parts or "\\" in entry["path"] or ":" in entry["path"]:
            raise RuntimeError("Unsafe KaTeX resource path")
        source = directory / str(path)
        if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(directory.resolve()):
            raise RuntimeError("Missing or external KaTeX resource")
        if sha256(source) != entry["sha256"]:
            raise RuntimeError("KaTeX resource checksum mismatch")
        files.add(source)
    actual = {path for path in directory.rglob("*") if path.is_file()}
    if files != actual or len(files) != len(entries) + 1:
        raise RuntimeError("KaTeX resource allowlist differs from the official download")
    return files


def allowed_source_files() -> list[Path]:
    files = [PROJECT / name for name in MODULES]
    katex = verified_katex_files()
    for directory, suffixes in [("static", {".html", ".css", ".js", ".svg", ".png", ".woff2"}),
                                 ("examples", {".json"})]:
        for path in (PROJECT / directory).rglob("*"):
            if path.is_file():
                relative = path.relative_to(PROJECT).as_posix()
                if FORBIDDEN.search(relative):
                    raise RuntimeError("User data reached the resource tree")
                if path not in katex and path.suffix.lower() not in suffixes:
                    raise RuntimeError(f"Unapproved resource extension: {path.name}")
                files.append(path)
    for path in files:
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(PROJECT):
            raise RuntimeError(f"Source is missing or is an external link: {path.name}")
        if set(path.relative_to(PROJECT).parts) & EXCLUDED:
            raise RuntimeError("Excluded directory reached the source allowlist")
    return sorted(files)


def icon_png(size: int) -> bytes:
    # A small vector-style learning path, rasterized without external assets.
    scale = 3
    large = size * scale
    points = [(0.27, 0.69), (0.50, 0.48), (0.73, 0.27)]
    background = (21, 42, 57, 255)
    edge = (91, 211, 198, 255)
    node = (232, 252, 249, 255)
    pixels = []
    for y in range(large):
        row = []
        for x in range(large):
            fx, fy = (x + .5) / large, (y + .5) / large
            color = background
            if min(fx, fy, 1 - fx, 1 - fy) < .08 and ((fx < .15 or fx > .85) and (fy < .15 or fy > .85)):
                corner_x, corner_y = (.15 if fx < .5 else .85), (.15 if fy < .5 else .85)
                if (fx - corner_x) ** 2 + (fy - corner_y) ** 2 > .15 ** 2:
                    color = (0, 0, 0, 0)
            for start, end in zip(points, points[1:]):
                dx, dy = end[0] - start[0], end[1] - start[1]
                t = max(0, min(1, ((fx - start[0]) * dx + (fy - start[1]) * dy) / (dx * dx + dy * dy)))
                if (fx - start[0] - t * dx) ** 2 + (fy - start[1] - t * dy) ** 2 <= .035 ** 2:
                    color = edge
            for px, py in points:
                distance = (fx - px) ** 2 + (fy - py) ** 2
                if distance <= .10 ** 2:
                    color = edge
                if distance <= .068 ** 2:
                    color = node
            row.append(color)
        pixels.append(row)
    rows = []
    for y in range(size):
        row = bytearray(b"\0")
        for x in range(size):
            samples = [pixels[y * scale + sy][x * scale + sx] for sy in range(scale) for sx in range(scale)]
            row.extend(round(sum(sample[channel] for sample in samples) / len(samples)) for channel in range(4))
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")


def write_icon(path: Path) -> None:
    sizes = [16, 32, 48, 128, 256]
    blobs = [icon_png(size) for size in sizes]
    offset = 6 + 16 * len(sizes)
    entries = []
    for size, data in zip(sizes, blobs):
        dimension = 0 if size == 256 else size
        entries.append(struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    path.write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries) + b"".join(blobs))


def license_notices(destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    summary = []
    files = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name", "unknown")
        if name.lower() in {"pip", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes", "setuptools"}:
            continue
        summary.append(f"{name} {distribution.version}")
        for file in distribution.files or []:
            if "licenses" in file.parts or file.name.lower() in {"license", "license.txt", "license.md", "copying"}:
                original = Path(distribution.locate_file(file))
                if original.is_file():
                    target = destination / name / file.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, target)
                    files.append(target)
    (destination / "PACKAGES.txt").write_text("Runtime dependency versions\n\n" + "\n".join(sorted(summary, key=str.casefold)) + "\n", encoding="utf-8")
    files.append(destination / "PACKAGES.txt")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, destination / "Python-LICENSE.txt")
        files.append(destination / "Python-LICENSE.txt")
    # PyInstaller's bootloader is shipped in each executable even though the
    # build tools themselves are not runtime packages.
    pyinstaller = importlib.metadata.distribution("pyinstaller")
    copying = next((Path(pyinstaller.locate_file(file)) for file in pyinstaller.files or []
                    if file.name == "COPYING.txt" and "licenses" in file.parts), None)
    if pyinstaller.version != "6.22.3" or copying is None or not copying.is_file():
        raise RuntimeError("The shipped PyInstaller bootloader requires its exact licensing notice")
    notices = [(copying, destination / "PyInstaller" / "COPYING.txt"),
               (PROJECT / PUBLIC_PROXY_LICENSE, destination / "proxy_tools" / "LICENSE.txt"),
               (PROJECT / "static/vendor/katex/LICENSE.txt", destination / "KaTeX" / "LICENSE.txt")]
    if importlib.metadata.version("proxy_tools") != "0.1.0" or sha256(PROJECT / PUBLIC_PROXY_LICENSE) != PUBLIC_PROXY_LICENSE_SHA256:
        raise RuntimeError("proxy_tools licensing notice does not match the verified installed release")
    for original, target in notices:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        files.append(target)
    summary.extend(["PyInstaller bootloader " + pyinstaller.version, "KaTeX 0.19.0"])
    (destination / "PACKAGES.txt").write_text("Runtime dependency versions and included bootloader\n\n" + "\n".join(sorted(summary, key=str.casefold)) + "\n", encoding="utf-8")
    return files


README = """MathPath 0.5.1 — Windows 桌面版

运行：双击 MathPath-desktop-0.5.1-windows-x64.exe。无需安装 Python，无需保持命令行窗口。
建议 Windows 10/11 64 位；需要 .NET Framework 4.6.2 或更新版本、Microsoft Edge WebView2 Runtime。
如果缺少 WebView2，可从微软官网安装：https://developer.microsoft.com/microsoft-edge/webview2/

第一次使用：选择同调、秩—零度或 ε–δ 极限，再点击“载入离线样例”。三套样例及学习卡无需登录。
要生成自己的图，点击软件菜单 MathPath → 模型/API 设置。
首次使用默认预填交大平台 DeepSeek：https://models.sjtu.edu.cn/api/v1，模型 deepseek-reasoner，
Chat Completions + JSON 对象。填写自己的交大平台 API 密钥并“保存并使用”；软件不内置共享密钥。
升级保留已保存的服务选择；需要切换时请选择“DeepSeek（交大平台，默认）”预设。
选择预设不自动保存、测试或生成；缺少密钥时提示配置，清除密钥后也不会自动切换其他模型。
可选择 ChatGPT 登录方式，或填写自己的兼容 API 地址、模型名称和 API 密钥后保存。
选择 ChatGPT 后，设置页会显示「登录 / 重新连接 ChatGPT」按钮；也可使用 MathPath → 连接 ChatGPT 菜单。
两处共用一个登录流程，授权在系统浏览器中进行。页面会显示本次登录状态，不显示账号或凭证。
登录不会自动保存服务选择或生成内容；连接后请明确保存要使用的服务。
保存配置本身不会发送模型请求；生成按钮、未缓存的学习卡及手动连接测试会调用所选服务。
生成内容仍需核对；图中先修关系属于教学建议。
知识点按图内顺序编号。样例学习卡内可展开先修简要讲解、查看结构示意图，
并完成附有提示与参考答案的后续练习；参考答案不会自动修改掌握标记。

历史 / 项目：成功载入的学习图自动成为一条本机历史，保存地图、学习卡、笔记、掌握标记、
作答、反馈、已用提示和复习时间。可建立项目，搜索历史，将所选历史移到项目或未分类。
项目和历史均可多选删除；删除项目前会确认，并保留里面的历史，将其移到未分类。
删除历史会同时删除这条历史的笔记、学习卡与作答，请先导出需要保留的记录。
删除当前历史后，已显示的图仍可查看或导出，但不会再次自动保存为已删除的记录。
多个窗口同时修改同一历史发生冲突时，会提示重新打开，不会静默覆盖较新的内容。

随时提问：右下角按钮打开可移动对话框。拖动标题栏移动，拖动右下角调整大小，
也可聚焦标题栏或调整手柄后按方向键操作。可以收起、关闭、重新打开或恢复位置。
选择整个学习目标或具体知识点后连续提问；AI 回答仅在点击发送时使用所选模型并消耗额度，
本地对照只提供已保存材料。AI 回答属于待核对建议，不会自动标记掌握或判定证明正确。
完成的问答随对应历史保存和导出，最多 100 轮，每次带上最多最近 10 轮上下文，长对话按长度减少。
切换历史不会混入另一条记录的问答；尚无学习历史时的临时问答只在当前页面保留。

未解决问题：回答失败、明确无法回答或待核对的问题会记入独立的问题历史；
也可手动点击“仍未解决”记录问题。无学习图时的问题也可保存，解决后由你标记已解决。
删除原学习历史仍保留问题和目标快照；不会把模型自报回答完成等同于数学正确。
目标过于宽泛时先展示几个具体方向，选择后再生成学习图。该本地预检查覆盖常见宽泛主题，
不能保证识别所有表达方式。选择证明与独立使用层级，或自报知识点三项都掌握后，
会显示经核对的参考书及官方来源；缺少适合当前主题的书目时会明确说明。

学习：图中包含可检查的目标、共同数学约定、诊断和最终检验，卡片可提供分级提示、
补步骤、独立题、回忆练习与混合练习。输入作答后，开放题的本地对照只提供参考要点，
不会自动认定你的证明正确。仅明确点击模型反馈时才生成待核对的候选意见。
AI 反馈仍需核对；一次答对不表示整个知识点已经掌握，模型反馈不会自动勾选掌握状态。
今天复习使用可调整的简单时间规则，不表示已经验证了长期学习效果。
公式排版及字体随软件提供，离线样例无需联网加载公式资源。
学习记录保存在本机，也可导出当前记录的 JSON 备份或在另一台电脑导入。
完整备份：在“历史 / 项目”点击“完整备份学习库”，保存全部项目、历史、笔记、问答及未解决问题。
“恢复完整备份”会先检查并展示数量，确认后追加新记录，保留本机已有记录；取消不会添加。
同一文件默认防止重复添加，确需重新找回后来删除的记录时可明确确认再次添加整份备份。
完整备份最大 50 MiB，不含账号、密钥或模型设置；换电脑后模型连接需单独配置。
旧版工作区会尝试保留并迁入一条历史；无法保存时旧版浏览器记录仍保留。
持久数据位于当前 Windows 用户的 %LOCALAPPDATA%\\MathPath，API 密钥与 ChatGPT 授权分别由 Windows DPAPI 加密保存。
设置页只显示是否已保存密钥，不回显密钥原文。发行文件不包含开发机器的配置或登录凭证。
关闭窗口会同时停止 MathPath 本机服务。
应用只监听 127.0.0.1。首次选出的空闲端口会被保留以恢复浏览器进度。
如果该端口被别的程序占用，MathPath 会提示先关闭占用程序；不会静默切换端口导致进度无法恢复。

离线自检（不登录、不调用模型）：
MathPath-desktop-0.5.1-windows-x64.exe --self-test --report self-test.json
真实窗口自检（会短暂打开并自动关闭窗口）：
MathPath-desktop-0.5.1-windows-x64.exe --smoke-window --report window-test.json

本版本是可运行原型。发行包尚未进行 Windows 代码签名。
第三方许可见 licenses 目录；构建与运行验证见同目录 JSON 报告。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise RuntimeError("Build on 64-bit Windows with the project Python environment")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    stem = f"MathPath-desktop-{VERSION}-windows-x64"
    release = output / stem
    release.mkdir(exist_ok=True)
    files = allowed_source_files()
    manifest = {"version": VERSION, "python": sys.version.split()[0],
                "pyinstaller": importlib.metadata.version("pyinstaller"),
                "source_files": [{"path": str(path.relative_to(PROJECT)).replace("\\", "/"), "sha256": sha256(path)} for path in files],
                "excluded_project_directories": sorted(EXCLUDED), "credentials_bundled": False}
    manifest["source_manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest["source_files"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest["build_files"] = [{"path": path, "sha256": sha256(PROJECT / path)}
                               for path in ["packaging/build.py", "packaging/build_setup.py", "packaging/installer.py",
                                            "requirements.txt", "desktop-requirements.txt", PUBLIC_PROXY_LICENSE]]
    source_report = output / (stem + "-source-check.json")
    source_window_report = output / (stem + "-source-window-check.json")
    subprocess.run([sys.executable, str(PROJECT / "desktop.py"), "--self-test", "--report", str(source_report)],
                   cwd=PROJECT, check=True, timeout=90)
    subprocess.run([sys.executable, str(PROJECT / "desktop.py"), "--smoke-window", "--report", str(source_window_report)],
                   cwd=PROJECT, check=True, timeout=90)
    for report_path in [source_report, source_window_report]:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["source_manifest_sha256"] = manifest["source_manifest_sha256"]
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["source_reports"] = [{"path": path.name, "sha256": sha256(path)}
                                  for path in [source_report, source_window_report]]
    # Build from a staged allowlist; the auth folder is never enumerated or read.
    with tempfile.TemporaryDirectory(prefix="mathpath-build-") as temporary:
        work = Path(temporary)
        stage = work / "source"
        for path in files:
            destination = stage / path.relative_to(PROJECT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            if sha256(destination) != next(item["sha256"] for item in manifest["source_files"]
                                           if item["path"] == path.relative_to(PROJECT).as_posix()):
                raise RuntimeError("Source changed while staging release")
        icon = stage / "mathpath.ico"
        write_icon(icon)
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
                   "--name", "MathPath", "--noupx", "--icon", str(icon), "--distpath", str(work / "dist"),
                   "--workpath", str(work / "build"), "--specpath", str(work), "--paths", str(stage),
                   "--add-data", str(stage / "static") + ":static", "--add-data", str(stage / "examples") + ":examples",
                   "--add-data", str(icon) + ":.", "--collect-data", "webview", "--collect-data", "pythonnet",
                   "--collect-data", "clr_loader", "--hidden-import", "uvicorn.logging",
                   "--hidden-import", "uvicorn.loops.asyncio", "--hidden-import", "uvicorn.protocols.http.h11_impl",
                   "--hidden-import", "uvicorn.lifespan.on", "--hidden-import", "anyio._backends._asyncio",
                   "--exclude-module", "PyQt5", "--exclude-module", "PyQt6", "--exclude-module", "PySide2",
                   "--exclude-module", "PySide6", "--exclude-module", "webview.platforms.cef",
                   "--exclude-module", "webview.platforms.qt", "--exclude-module", "webview.platforms.gtk",
                   str(stage / "desktop.py")]
        subprocess.run(command, cwd=stage, check=True)
        executable = output / (stem + ".exe")
        shutil.copy2(work / "dist" / "MathPath.exe", executable)
        from PyInstaller.archive.readers import CArchiveReader
        entries = list(CArchiveReader(str(executable)).toc)
        if any(FORBIDDEN.search(name.replace("\\", "/")) for name in entries):
            raise RuntimeError("Excluded data reached the executable archive")
        manifest["archive_entries_checked"] = len(entries)
        manifest["excluded_data_absent"] = True
        shutil.copy2(executable, release / executable.name)
    (release / "README-中文.txt").write_text(README, encoding="utf-8-sig")
    license_files = license_notices(release / "licenses")
    report_file = release / "self-test.json"
    subprocess.run([str(executable), "--self-test", "--report", str(report_file)], check=True, timeout=90)
    window_report = release / "window-test.json"
    subprocess.run([str(executable), "--smoke-window", "--report", str(window_report)], check=True, timeout=90)
    manifest.update({"executable": executable.name, "executable_bytes": executable.stat().st_size,
                     "executable_sha256": sha256(executable)})
    verify_sources(files, manifest["source_files"])
    for report_path in [report_file, window_report]:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report.update({"executable_sha256": manifest["executable_sha256"],
                       "source_manifest_sha256": manifest["source_manifest_sha256"]})
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    release_files = [release / executable.name, release / "README-中文.txt", report_file, window_report, release / "manifest.json"] + license_files
    manifest["release_files"] = sorted({str(path.relative_to(release)).replace("\\", "/") for path in release_files})
    manifest_file = output / (stem + "-manifest.json")
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(manifest_file, release / "manifest.json")
    release_allowlist(manifest, release)
    archive = output / (stem + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for relative in manifest["release_files"]:
            path = release / relative
            bundle.write(path, Path(stem) / relative)
    with zipfile.ZipFile(archive) as bundle:
        expected = {stem + "/" + relative for relative in manifest["release_files"]}
        if set(bundle.namelist()) != expected:
            raise RuntimeError("ZIP release allowlist verification failed")
        if any(FORBIDDEN.search(name) for name in bundle.namelist()):
            raise RuntimeError("Excluded data reached the ZIP release")
    print(json.dumps({"executable": str(executable), "bytes": executable.stat().st_size,
                      "archive": str(archive), "zip_allowlist_verified": True,
                      "self_test": json.loads(report_file.read_text(encoding="utf-8"))}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
