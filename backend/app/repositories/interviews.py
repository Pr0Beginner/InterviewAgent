from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.app.models import ApplicationStatusHistory, JobApplication
from backend.app.models.enums import INTERVIEW_STATUS_VALUES


@dataclass(slots=True)
class InterviewPage:
    """用于构建面试分页响应的数据库查询结果。"""
    items: list[JobApplication]
    total: int
    summary_total: int
    status_counts: dict[str, int]


class InterviewRepository:
    """投递记录及其状态历史的持久化操作。"""

    def __init__(self, session: Session) -> None:
        """初始化数据仓储。
        
        参数:
            session: 请求级 SQLAlchemy 会话。
        """
        self.session = session

    def list_page(
        self,
        *,
        company_name: str | None,
        position_name: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> InterviewPage:
        """使用相同的文本筛选条件查询一页记录及状态汇总。
        
        参数:
            company_name: 可选的公司名称包含匹配条件。
            position_name: 可选的岗位名称包含匹配条件。
            status: 仅作用于分页记录的可选精确状态筛选条件。
            page: 页码，从 1 开始。
            page_size: 每页最多返回的记录数。
        
        返回值:
            分页记录、筛选后的总数，以及应用状态筛选前的汇总数量。
        """
        base_filters = []
        if company_name:
            base_filters.append(
                JobApplication.company_name.contains(company_name, autoescape=True)
            )
        if position_name:
            base_filters.append(
                JobApplication.position_name.contains(position_name, autoescape=True)
            )

        summary_total = self.session.scalar(
            select(func.count(JobApplication.id)).where(*base_filters)
        ) or 0
        grouped_counts = self.session.execute(
            select(JobApplication.current_status, func.count(JobApplication.id))
            .where(*base_filters)
            .group_by(JobApplication.current_status)
        ).all()
        status_counts = {value: 0 for value in INTERVIEW_STATUS_VALUES}
        status_counts.update({current_status: count for current_status, count in grouped_counts})

        item_filters = list(base_filters)
        if status:
            item_filters.append(JobApplication.current_status == status)

        total = self.session.scalar(
            select(func.count(JobApplication.id)).where(*item_filters)
        ) or 0
        items = list(
            self.session.scalars(
                select(JobApplication)
                .where(*item_filters)
                .order_by(
                    case((JobApplication.interview_time.is_(None), 1), else_=0),
                    JobApplication.interview_time.desc(),
                    JobApplication.id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return InterviewPage(
            items=items,
            total=total,
            summary_total=summary_total,
            status_counts=status_counts,
        )

    def get(self, interview_id: int) -> JobApplication | None:
        """根据主键查询一条投递记录。
        
        参数:
            interview_id: 投递记录 ID。
        
        返回值:
            匹配的投递记录；不存在时返回 None。
        """
        return self.session.get(JobApplication, interview_id)

    def add_status_history(
        self,
        *,
        application_id: int,
        previous_status: str | None,
        current_status: str,
        change_source: str,
        note: str | None,
    ) -> None:
        """在当前事务中暂存一条状态历史记录。
        
        参数:
            application_id: 所属投递记录的 ID。
            previous_status: 变更前的状态；没有旧状态时为空。
            current_status: 变更后的状态。
            change_source: 发起变更的用户或外部集成来源。
            note: 与本次变更相关的可选说明。
        """
        self.session.add(
            ApplicationStatusHistory(
                application_id=application_id,
                previous_status=previous_status,
                current_status=current_status,
                change_source=change_source,
                note=note,
            )
        )
