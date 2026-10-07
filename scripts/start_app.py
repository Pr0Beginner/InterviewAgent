"""在 Windows 上统一启动后端服务和桌面客户端。"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


项目目录 = Path(__file__).resolve().parent.parent
前端目录 = 项目目录 / "frontend"
健康检查地址 = "http://127.0.0.1:8000/api/health"
后端端口 = 8000
后端服务名 = "Interview Assistant API"


def 后端健康() -> bool:
    """检查 8000 端口响应的是否为本项目后端。"""
    try:
        with urllib.request.urlopen(健康检查地址, timeout=1) as response:
            内容 = json.loads(response.read().decode("utf-8"))
            return (
                response.status == 200
                and 内容.get("status") == "ok"
                and 内容.get("service") == 后端服务名
            )
    except (OSError, ValueError, urllib.error.URLError):
        return False


def 停止已运行后端() -> list[int]:
    """停止本项目健康接口所在端口的监听进程，不按 Python 进程名批量结束。"""
    powershell = (
        f"$owners = @(Get-NetTCPConnection -LocalPort {后端端口} -State Listen "
        "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique); "
        "if ($owners.Count -eq 0) { exit 3 }; "
        "foreach ($processId in $owners) { "
        "Stop-Process -Id $processId -Force -ErrorAction Stop }; "
        "$owners -join ','"
    )
    结果 = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            powershell,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if 结果.returncode != 0:
        详情 = 结果.stderr.strip() or "没有找到监听进程"
        raise RuntimeError(f"无法停止已运行的后端：{详情}")

    进程号 = [int(value) for value in 结果.stdout.strip().split(",") if value.strip()]
    for _ in range(30):
        if not 后端健康():
            return 进程号
        time.sleep(0.1)
    raise RuntimeError("旧后端已请求停止，但 8000 端口仍未释放。")


def 启动后端() -> subprocess.Popen[bytes]:
    """在后台启动 FastAPI，并等待健康检查成功。"""
    进程 = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        cwd=项目目录,
    )

    for _ in range(40):
        if 后端健康():
            return 进程
        if 进程.poll() is not None:
            raise RuntimeError(f"后端启动失败，退出码：{进程.returncode}")
        time.sleep(0.25)

    结束进程(进程)
    raise RuntimeError("后端在 10 秒内未通过健康检查。")


def 结束进程(进程: subprocess.Popen[bytes] | None) -> None:
    """只结束由本次脚本启动的后端进程。"""
    if 进程 is None or 进程.poll() is not None:
        return
    进程.terminate()
    try:
        进程.wait(timeout=5)
    except subprocess.TimeoutExpired:
        进程.kill()
        进程.wait(timeout=5)


def main() -> int:
    """启动后端并打开 PySide6 客户端。"""
    后端进程: subprocess.Popen[bytes] | None = None
    try:
        if 后端健康():
            print("[INFO] 检测到后端已经运行，正在停止旧实例。")
            进程号 = 停止已运行后端()
            print(f"[INFO] 已停止旧后端进程：{', '.join(map(str, 进程号))}")

        后端进程 = 启动后端()
        print("[INFO] 后端已重新启动。")

        客户端结果 = subprocess.run(
            [sys.executable, "-m", "client.main"],
            cwd=前端目录,
            check=False,
        )
        return 客户端结果.returncode
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    finally:
        结束进程(后端进程)


if __name__ == "__main__":
    raise SystemExit(main())
