"""Windows 启动入口：复用已运行的 MathPath，或启动后打开页面。"""

import json
from pathlib import Path
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn

PROJECT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8000/"


def mathpath_is_running():
    # 本机请求直接走回环地址，不受外部模型代理影响。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(URL + "health", timeout=1) as response:
            if json.load(response) != {"status": "ok"}:
                return False
        with opener.open(URL, timeout=1) as response:
            return b"<title>MathPath" in response.read(4096)
    except (OSError, ValueError, urllib.error.URLError):
        return False


def open_when_ready():
    for _ in range(40):
        if mathpath_is_running():
            webbrowser.open(URL)
            return
        time.sleep(0.25)


def main():
    if mathpath_is_running():
        print("MathPath 已在运行，正在打开页面：" + URL)
        webbrowser.open(URL)
        return
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            print("8000 端口正在被其他服务使用。请先停止该服务，再启动 MathPath。")
            raise SystemExit(1)
    except OSError:
        pass
    print("MathPath 启动后会自动打开：" + URL, flush=True)
    print("保持此窗口开启；按 Ctrl+C 停止服务。", flush=True)
    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run("main:app", app_dir=str(PROJECT), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
