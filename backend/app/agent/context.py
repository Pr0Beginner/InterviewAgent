"""服务端保存的轻量工具上下文；完整对话历史仍由客户端维护。"""

import json
import sqlite3
from hashlib import sha256
from pathlib import Path

from backend.app.db.state import get_langgraph_sqlite_path


class ToolContextStore:
    """跨 ReAct 轮次保存会话、题目和任务 ID，并按页面隔离。"""

    def __init__(self, path=None):
        """使用配置的 SQLite 状态文件；测试时可传入独立路径。"""
        self.path = Path(path or get_langgraph_sqlite_path())

    def _connect(self):
        """打开设置了等待超时的 SQLite 连接，仅初始化本模块的数据表。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.execute("CREATE TABLE IF NOT EXISTS agent_tool_context (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        return connection

    @staticmethod
    def key(metadata):
        """根据调用方的会话 ID 和当前页面生成存储键，不将其作为文件路径。"""
        conversation = metadata.get("conversation_id")
        if not conversation:
            return None
        return sha256((conversation + "\0" + metadata.get("page_context", "applications")).encode()).hexdigest()

    def read(self, key):
        """仅读取已保存的标识，不存储邮件、凭证或模型推理内容。"""
        if key is None:
            return {}
        connection = self._connect()
        try:
            row = connection.execute("SELECT value FROM agent_tool_context WHERE id = ?", (key,)).fetchone()
            return json.loads(row[0]) if row else {}
        finally:
            connection.close()

    def record(self, key, tool_name, result):
        """记录工具成功返回的 ID，不直接信任用户提供的 ID。"""
        if key is None or "error" in result:
            return
        changes = {}
        if tool_name == "start_mock_interview":
            changes = {"mock_session_id": result["session_id"], "question_id": result["question_id"]}
        elif tool_name == "submit_mock_answer":
            changes = {"question_id": result.get("question_id")}
        elif tool_name == "finish_mock_interview":
            changes = {"mock_session_id": None, "question_id": None}
        elif tool_name in {"scan_emails", "scan_unread_emails"}:
            changes = {"mail_task_id": result["task_id"]}
        if not changes:
            return
        connection = self._connect()
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute("SELECT value FROM agent_tool_context WHERE id = ?", (key,)).fetchone()
                context = json.loads(row[0]) if row else {}
                context.update(changes)
                connection.execute("INSERT INTO agent_tool_context VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET value=excluded.value", (key, json.dumps(context)))
        finally:
            connection.close()
