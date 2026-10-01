from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base
from backend.app.models.enums import INTERVIEW_STATUS_CHECK_SQL

BIGINT_ID = BigInteger().with_variant(Integer, "sqlite")


class JobApplication(Base):
    """桌面表格展示的投递记录当前状态。"""
    __tablename__ = "job_applications"
    __table_args__ = (
        CheckConstraint(INTERVIEW_STATUS_CHECK_SQL, name="valid_status"),
        Index("ix_job_applications_company_position", "company_name", "position_name"),
        Index("ix_job_applications_status_time", "current_status", "interview_time"),
        {
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(BIGINT_ID, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    position_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_location: Mapped[str] = mapped_column(String(100), nullable=False)
    current_status: Mapped[str] = mapped_column(String(32), nullable=False)
    interview_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    job_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    status_history: Mapped[list[ApplicationStatusHistory]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ApplicationStatusHistory.changed_at",
    )


class ApplicationStatusHistory(Base):
    """投递状态变化时写入的不可变审计记录。"""
    __tablename__ = "application_status_history"
    __table_args__ = (
        CheckConstraint(INTERVIEW_STATUS_CHECK_SQL, name="valid_status"),
        Index(
            "ix_application_status_history_application_time",
            "application_id",
            "changed_at",
        ),
        {
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(BIGINT_ID, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        BIGINT_ID,
        ForeignKey("job_applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    current_status: Mapped[str] = mapped_column(String(32), nullable=False)
    change_source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="user"
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )

    application: Mapped[JobApplication] = relationship(back_populates="status_history")
