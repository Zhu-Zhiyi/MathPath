"""Per-user Windows installer: no administrator rights, no credential access."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile

PAYLOAD = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "payload"
VERSION = "0.5.0"
EXECUTABLE = f"MathPath-desktop-{VERSION}-windows-x64.exe"
FORBIDDEN = re.compile(r"(^|/)(\.mathpath|\.venv|EBWebView|WebView2UserData)(/|$)|chatgpt_session\.dpapi|api_settings\.dpapi|host_id\.json|\.(sqlite3?|db)(?:[-.]|$)|(^|/)(desktop|state|workspace|progress)\.json$", re.IGNORECASE)


def notify(text: str, warning: bool = False) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "MathPath 安装", 0x10 if warning else 0x40)


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_shortcuts(executable: Path, test_directory: Path | None = None) -> list[Path]:
    # Paths are structured subprocess arguments, never shell-built commands.
    script = r"""param([string]$Executable, [string]$TestDirectory)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$shell = New-Object -ComObject WScript.Shell
if ($TestDirectory) {
    $desktopFolder = Join-Path $TestDirectory 'Desktop'
    $programsFolder = Join-Path $TestDirectory 'Programs'
    [void](New-Item -ItemType Directory -Path $desktopFolder -Force)
    [void](New-Item -ItemType Directory -Path $programsFolder -Force)
} else {
    $desktopFolder = $shell.SpecialFolders.Item('Desktop')
    $programsFolder = $shell.SpecialFolders.Item('Programs')
}
$shortcutFiles = @((Join-Path $desktopFolder 'MathPath.lnk'), (Join-Path $programsFolder 'MathPath.lnk'))
foreach ($shortcutFile in $shortcutFiles) {
    $shortcut = $shell.CreateShortcut($shortcutFile)
    $shortcut.TargetPath = $Executable
    $shortcut.WorkingDirectory = [System.IO.Path]::GetDirectoryName($Executable)
    $shortcut.IconLocation = $Executable + ',0'
    $shortcut.Description = 'MathPath 数学学习路径'
    $shortcut.Save()
    if ($shell.CreateShortcut($shortcutFile).TargetPath -ne $Executable) { throw 'shortcut-verification-failed' }
}
ConvertTo-Json -InputObject $shortcutFiles -Compress
"""
    with tempfile.TemporaryDirectory(prefix="mathpath-shortcuts-") as temporary:
        script_path = Path(temporary) / "shortcuts.ps1"
        script_path.write_text(script, encoding="utf-8-sig")
        powershell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        args = [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(script_path), "-Executable", str(executable)]
        if test_directory:
            args += ["-TestDirectory", str(test_directory)]
        result = subprocess.run(args, check=True, capture_output=True, encoding="utf-8",
                                creationflags=subprocess.CREATE_NO_WINDOW)
    return [Path(path) for path in json.loads(result.stdout)]


def install(destination: Path, test_shortcuts: Path | None = None) -> dict:
    manifest = json.loads((PAYLOAD / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != VERSION:
        raise RuntimeError("payload-version-mismatch")
    release_files = manifest.get("release_files")
    required = {EXECUTABLE, "README-中文.txt", "manifest.json", "self-test.json", "window-test.json"}
    if (not isinstance(release_files, list) or not all(isinstance(path, str) for path in release_files)
            or len(set(release_files)) != len(release_files) or not required.issubset(release_files)):
        raise RuntimeError("payload-allowlist-missing")
    for relative in release_files:
        path = PurePosixPath(relative)
        if (path.is_absolute() or str(path) != relative or ".." in path.parts
                or "\\" in relative or ":" in relative
                or FORBIDDEN.search(relative)
                or (relative not in required and not (len(path.parts) >= 2 and path.parts[0] == "licenses"))):
            raise RuntimeError("unsafe-payload-path")
        original = PAYLOAD / relative
        if (not original.is_file() or original.is_symlink()
                or not original.resolve().is_relative_to(PAYLOAD.resolve())):
            raise RuntimeError("payload-file-missing")
    source = PAYLOAD / EXECUTABLE
    if hash_file(source) != manifest["executable_sha256"]:
        raise RuntimeError("payload-verification-failed")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "MathPath.exe"
    # Keep application data separate from program files. Neither installation
    # nor upgrade enumerates, overwrites or deletes MathPath's user-data folder.
    pending = destination / "MathPath.exe.pending"
    shutil.copy2(source, pending)
    if hash_file(pending) != manifest["executable_sha256"]:
        raise RuntimeError("installed-file-verification-failed")
    pending.replace(target)
    for relative in release_files:
        if relative in {"README-中文.txt", "manifest.json"} or PurePosixPath(relative).parts[0] == "licenses":
            installed_file = destination / relative
            installed_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PAYLOAD / relative, installed_file)
    if hash_file(target) != manifest["executable_sha256"]:
        raise RuntimeError("installed-file-verification-failed")
    shortcuts = create_shortcuts(target, test_shortcuts)
    if not all(path.is_file() for path in shortcuts):
        raise RuntimeError("shortcut-missing")
    return {"status": "ok", "version": VERSION, "installed_executable": str(target),
            "shortcuts": [str(path) for path in shortcuts], "sha256": manifest["executable_sha256"],
            "administrator_required": False, "user_data_modified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Install MathPath for the current Windows user")
    parser.add_argument("--quiet", action="store_true", help="install without dialogs")
    parser.add_argument("--self-test", action="store_true", help="verify installation and shortcuts in a temporary directory")
    parser.add_argument("--report", help="write a safe JSON report")
    args = parser.parse_args()
    report = {}
    code = 0
    try:
        if args.self_test:
            with tempfile.TemporaryDirectory(prefix="mathpath-installer-check-") as temporary:
                # Exercise non-ASCII paths even on an ASCII-named Windows user.
                base = Path(temporary) / "安装测试"
                base.mkdir()
                user_data = base / "MathPath-user-data"
                user_data.mkdir()
                marker = user_data / "progress-sentinel.txt"
                marker.write_text("keep-this-user-data", encoding="utf-8")
                report = install(base / "Programs" / "MathPath", base / "shortcuts")
                # Exercise an upgrade; user-data remains untouched.
                install(base / "Programs" / "MathPath", base / "shortcuts")
                if marker.read_text(encoding="utf-8") != "keep-this-user-data":
                    raise RuntimeError("user-data-preservation-failed")
                app_report = base / "app-check.json"
                subprocess.run([report["installed_executable"], "--self-test", "--report", str(app_report)], check=True, timeout=90)
                app_result = json.loads(app_report.read_text(encoding="utf-8"))
                if (app_result.get("status") != "ok" or app_result.get("version") != VERSION
                        or not app_result.get("server_stopped")):
                    raise RuntimeError("installed-application-check-failed")
                report.update({"test_mode": True, "upgrade_verified": True, "user_data_preserved": True,
                               "installed_application_self_test": app_result})
        else:
            local = Path(os.environ["LOCALAPPDATA"]).resolve()
            destination = local / "Programs" / "MathPath"
            if not args.quiet:
                response = ctypes.windll.user32.MessageBoxW(None,
                    "安装 MathPath 到当前 Windows 用户的应用目录，并创建桌面和开始菜单快捷方式。\n\n"
                    "无需管理员权限。升级会保留学习进度与登录数据。\n\n点击「确定」安装。",
                    "MathPath 安装", 0x41)
                if response != 1:
                    return 0
            report = install(destination)
            if not args.quiet:
                notify("MathPath 已安装。\n\n请双击桌面上的 MathPath 快捷方式打开。")
    except Exception as exc:
        code = 1
        report = {"status": "failed", "error": type(exc).__name__}
        if not args.quiet and not args.self_test:
            notify("安装未完成。请先关闭正在运行的 MathPath，然后重新运行安装包。", warning=True)
    if args.report:
        Path(args.report).resolve().write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if sys.stdout is not None:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
