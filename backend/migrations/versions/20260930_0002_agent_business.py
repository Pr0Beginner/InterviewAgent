"""持久化 Agent 操作、同步凭据、任务和面试会话。"""

import sqlalchemy as sa
from alembic import op

revision = "20260930_0002"
down_revision = "20260930_0001"
branch_labels = None
depends_on = None


def upgrade():
    """新增业务表，不改写已有投递记录。"""
    options = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}
    op.create_table("agent_operations", sa.Column("id", sa.String(64), primary_key=True), sa.Column("result", sa.JSON(), nullable=False), **options)
    op.create_table("feishu_sync_items",
        sa.Column("application_id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("last_error", sa.Text()), **options)
    op.create_table("email_receipts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("application_id", sa.Integer()),
        sa.Column("processed_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), **options)
    op.create_table("task_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False), sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), **options)
    op.create_index("ix_task_runs_kind", "task_runs", ["kind"])
    op.create_table("mock_interview_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False), sa.Column("turns", sa.JSON(), nullable=False),
        sa.Column("report", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), **options)


def downgrade():
    """仅删除本次迁移新增的业务表。"""
    for name in ("mock_interview_sessions", "task_runs", "email_receipts", "feishu_sync_items", "agent_operations"):
        op.drop_table(name)
