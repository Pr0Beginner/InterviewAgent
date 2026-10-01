"""将已投递和待面试加入投递状态。"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261001_0003"
down_revision: str | None = "20260930_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUS_CHECK = (
    "current_status IN ('简历筛选中', '笔试中', '一面', '二面', "
    "'三面', 'HR面', 'Offer', '已结束')"
)
NEW_STATUS_CHECK = (
    "current_status IN ('已投递', '简历筛选中', '笔试中', '待面试', '一面', '二面', "
    "'三面', 'HR面', 'Offer', '已结束')"
)


def _replace_status_checks(expression: str) -> None:
    """用给定状态约束同时更新当前记录表和历史表。"""
    for table_name in ("job_applications", "application_status_history"):
        constraint_name = f"ck_{table_name}_valid_status"
        # op.f 标记名称已经过命名约定处理，避免再次添加表名前缀。
        formatted_name = op.f(constraint_name)
        op.drop_constraint(formatted_name, table_name, type_="check")
        op.create_check_constraint(formatted_name, table_name, expression)


def upgrade() -> None:
    """允许当前状态及状态历史保存“已投递”和“待面试”。"""
    _replace_status_checks(NEW_STATUS_CHECK)


def downgrade() -> None:
    """回退前归并新增状态，再恢复旧状态约束。"""
    op.execute("UPDATE job_applications SET current_status = '简历筛选中' WHERE current_status = '已投递'")
    op.execute("UPDATE application_status_history SET current_status = '简历筛选中' WHERE current_status = '已投递'")
    op.execute("UPDATE job_applications SET current_status = '一面' WHERE current_status = '待面试'")
    op.execute("UPDATE application_status_history SET current_status = '一面' WHERE current_status = '待面试'")
    _replace_status_checks(OLD_STATUS_CHECK)
