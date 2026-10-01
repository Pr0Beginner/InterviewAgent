"""为投递记录增加笔试或面试结束时间。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_0004"
down_revision: str | None = "20261001_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增可为空的结束时间，已有记录保持为空。"""
    op.add_column(
        "job_applications",
        sa.Column("interview_end_time", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """移除结束时间字段。"""
    op.drop_column("job_applications", "interview_end_time")
