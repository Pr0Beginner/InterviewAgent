"""推荐岗位页的长期偏好摘要与六轮更新进度。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, Field

from backend.app.db.state import get_langgraph_sqlite_path


PREFERENCE_MEMORY_INSTRUCTIONS = """
你负责更新用户的岗位偏好长期记忆。结合上一版摘要和最近六轮对话，只总结用户明确表达或反复确认的偏好，
例如岗位方向、业务类型、城市、薪资倾向、公司类型、工作方式和明确排斥项。
助手说过的话只能用于理解上下文，不能当成用户偏好。不得猜测，不记录临时问题、具体投递动作或敏感信息。
输出一段连贯中文，不使用列表或 Markdown，不超过100个汉字；没有新增偏好时保留仍然有效的旧摘要。
""".strip()


class JobPreferenceSummary(BaseModel):
    summary: str = Field(default="", max_length=100)


class JobPreferenceMemoryStore:
    """在应用既有 SQLite 中保存单用户岗位偏好和每个会话的更新进度。"""

    PROFILE_ID = "local-user-job-preferences"

    def __init__(self, path=None):
        self.path = Path(path or get_langgraph_sqlite_path())

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.execute(
            """CREATE TABLE IF NOT EXISTS agent_job_preference_memory (
                id TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS agent_job_preference_progress (
                conversation_key TEXT PRIMARY KEY,
                summarized_user_turns INTEGER NOT NULL
            )"""
        )
        return connection

    @staticmethod
    def conversation_key(metadata: dict[str, str]) -> str | None:
        """只为带稳定会话 ID 的推荐岗位页面生成进度键。"""
        conversation_id = metadata.get("conversation_id")
        if metadata.get("page_context") != "recommendations" or not conversation_id:
            return None
        return sha256((conversation_id + "\0recommendations").encode()).hexdigest()

    def read_summary(self) -> str:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT summary FROM agent_job_preference_memory WHERE id = ?",
                (self.PROFILE_ID,),
            ).fetchone()
            return row[0] if row else ""
        finally:
            connection.close()

    def read_progress(self, conversation_key: str | None) -> int:
        if conversation_key is None:
            return 0
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT summarized_user_turns FROM agent_job_preference_progress WHERE conversation_key = ?",
                (conversation_key,),
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            connection.close()

    def save(self, conversation_key: str, summary: str, summarized_user_turns: int) -> None:
        """在同一事务中更新摘要和该会话已覆盖的用户轮次。"""
        if len(summary) > 100:
            raise ValueError("岗位偏好摘要不能超过100个字符")
        connection = self._connect()
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """INSERT INTO agent_job_preference_memory (id, summary, updated_at)
                       VALUES (?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET summary=excluded.summary, updated_at=excluded.updated_at""",
                    (self.PROFILE_ID, summary, datetime.now(timezone.utc).isoformat()),
                )
                connection.execute(
                    """INSERT INTO agent_job_preference_progress (conversation_key, summarized_user_turns)
                       VALUES (?, ?)
                       ON CONFLICT(conversation_key) DO UPDATE
                       SET summarized_user_turns=excluded.summarized_user_turns""",
                    (conversation_key, summarized_user_turns),
                )
        finally:
            connection.close()
