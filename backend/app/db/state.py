from pathlib import Path

from backend.app.core.config import get_settings


def get_langgraph_sqlite_path() -> Path:
    """返回 LangGraph 的 SQLite 文件路径，并创建其父目录。"""
    path = get_settings().langgraph_sqlite_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
