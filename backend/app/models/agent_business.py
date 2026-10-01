"""业务持久化模型，不保存邮件正文。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class AgentOperation(Base):
    """与业务写入在同一事务中提交的幂等执行凭据。"""
    __tablename__ = "agent_operations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)


class FeishuSyncItem(Base):
    """将单条投递记录同步到飞书时使用的持久化重试项。"""
    __tablename__ = "feishu_sync_items"
    application_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)


class EmailReceipt(Base):
    """最小化的邮件标识和处理结果，不包含主题或正文。"""
    __tablename__ = "email_receipts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    application_id: Mapped[int | None] = mapped_column(Integer)
    processed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class TaskRun(Base):
    """持久化的邮件任务状态和缓存的岗位推荐快照。"""
    __tablename__ = "task_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class MockInterviewSession(Base):
    """模型生成的题目、用户提交的回答和最终总结。"""
    __tablename__ = "mock_interview_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="in_progress", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False)
    turns: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    report: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
