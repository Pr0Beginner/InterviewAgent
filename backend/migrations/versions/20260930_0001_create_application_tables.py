"""创建投递相关数据表

迁移版本 ID: 20260930_0001
前置版本:
创建时间: 2026-09-30 16:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS_CHECK = (
    "current_status IN ('简历筛选中', '笔试中', '一面', '二面', "
    "'三面', 'HR面', 'Offer', '已结束')"
)


def upgrade() -> None:
    """创建投递记录表和投递状态历史表。"""
    op.create_table(
        "job_applications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("position_name", sa.String(length=255), nullable=False),
        sa.Column("base_location", sa.String(length=100), nullable=False),
        sa.Column("current_status", sa.String(length=32), nullable=False),
        sa.Column("interview_time", sa.DateTime(), nullable=True),
        sa.Column("job_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            STATUS_CHECK,
            name=op.f("ck_job_applications_valid_status"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_job_applications"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_job_applications_company_position",
        "job_applications",
        ["company_name", "position_name"],
        unique=False,
    )
    op.create_index(
        "ix_job_applications_status_time",
        "job_applications",
        ["current_status", "interview_time"],
        unique=False,
    )

    op.create_table(
        "application_status_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("current_status", sa.String(length=32), nullable=False),
        sa.Column(
            "change_source",
            sa.String(length=32),
            server_default="user",
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            STATUS_CHECK,
            name=op.f("ck_application_status_history_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["job_applications.id"],
            name="fk_application_status_history_application_id_job_applications",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_application_status_history"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_application_status_history_application_time",
        "application_status_history",
        ["application_id", "changed_at"],
        unique=False,
    )


def downgrade() -> None:
    """删除本次迁移创建的投递相关数据表。"""
    op.drop_index(
        "ix_application_status_history_application_time",
        table_name="application_status_history",
    )
    op.drop_table("application_status_history")
    op.drop_index("ix_job_applications_status_time", table_name="job_applications")
    op.drop_index(
        "ix_job_applications_company_position",
        table_name="job_applications",
    )
    op.drop_table("job_applications")
