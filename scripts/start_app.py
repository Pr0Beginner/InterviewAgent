"""在 Windows 上统一启动数据库迁移、后端服务和桌面客户端。"""

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


def 后端健康() -> bool:
    """检查本地后端是否已经启动并正常响应。"""
    try:
        with urllib.request.urlopen(健康检查地址, timeout=1) as response:
            内容 = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and 内容.get("status") == "ok"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def 执行数据库迁移() -> None:
    """将本地 MySQL 表结构升级到当前代码要求的版本。"""
    结果 = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
        cwd=项目目录,
        check=False,
    )
    if 结果.returncode != 0:
        raise RuntimeError("数据库迁移失败。")


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
    """依次执行迁移、启动后端并打开 PySide6 客户端。"""
    后端进程: subprocess.Popen[bytes] | None = None
    try:
        执行数据库迁移()
        if 后端健康():
            print("[INFO] 检测到后端已经运行，将直接复用。")
        else:
            后端进程 = 启动后端()
            print("[INFO] 后端启动成功。")

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
