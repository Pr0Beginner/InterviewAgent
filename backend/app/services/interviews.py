from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.exceptions import ApplicationError
from backend.app.models import JobApplication
from backend.app.repositories.interviews import InterviewPage, InterviewRepository
from backend.app.schemas.interviews import InterviewStatusUpdateRequest, InterviewUpdateRequest
from backend.app.services.sync import queue_sync

logger = logging.getLogger(__name__)


class InterviewService:
    """查询和更新投递进度的业务操作。"""

    def __init__(self, session: Session) -> None:
        """初始化业务服务。
        
        参数:
            session: 当前请求使用的 SQLAlchemy 会话，对应一次事务。
        """
        self.session = session
        self.repository = InterviewRepository(session)

    def list_interviews(
        self,
        *,
        company_name: str | None,
        position_name: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> InterviewPage:
        """返回筛选后的投递分页。
        
        参数:
            company_name: 可选的公司名称包含匹配条件。
            position_name: 可选的岗位名称包含匹配条件。
            status: 可选的精确状态筛选条件。
            page: 页码，从 1 开始。
            page_size: 每页最多返回的记录数。
        
        返回值:
            仓储返回的分页结果，包含记录及汇总数量。
        """
        return self.repository.list_page(
            company_name=company_name,
            position_name=position_name,
            status=status,
            page=page,
            page_size=page_size,
        )

    def update_interview(
        self, interview_id: int, request: InterviewUpdateRequest
    ) -> JobApplication:
        """替换一条投递记录的可编辑字段。
        
        参数:
            interview_id: 投递记录 ID。
            request: 客户端提交并经过校验的可编辑字段。
        
        返回值:
            事务提交后重新加载的投递记录。
        
        异常:
            ApplicationError: 记录不存在或写入失败时抛出。
        """
        application = self._get_or_raise(interview_id)
        previous_status = application.current_status

        application.company_name = request.company_name
        application.position_name = request.position_name
        application.base_location = request.base_location
        application.current_status = request.current_status.value
        application.interview_time = request.interview_time
        application.updated_at = request.updated_at

        if previous_status != application.current_status:
            self.repository.add_status_history(
                application_id=application.id,
                previous_status=previous_status,
                current_status=application.current_status,
                change_source="user",
                note=None,
            )

        self._commit(application)
        return application

    def update_status(
        self, interview_id: int, request: InterviewStatusUpdateRequest
    ) -> tuple[JobApplication, str]:
        """仅更新投递状态和可选的面试时间。
        
        参数:
            interview_id: 投递记录 ID。
            request: 已校验的状态更新请求。
        
        返回值:
            包含更新后投递记录和变更前状态的二元组。
        
        异常:
            ApplicationError: 记录不存在或写入失败时抛出。
        """
        application = self._get_or_raise(interview_id)
        previous_status = application.current_status
        application.current_status = request.target_status.value
        if "interview_time" in request.model_fields_set:
            application.interview_time = request.interview_time
        application.updated_at = datetime.now()

        if previous_status != application.current_status:
            self.repository.add_status_history(
                application_id=application.id,
                previous_status=previous_status,
                current_status=application.current_status,
                change_source="user",
                note=request.note,
            )

        self._commit(application)
        return application, previous_status

    def _get_or_raise(self, interview_id: int) -> JobApplication:
        """返回投递记录，不存在时抛出统一的记录未找到异常。
        
        参数:
            interview_id: 投递记录 ID。
        
        返回值:
            已存在的投递记录。
        """
        application = self.repository.get(interview_id)
        if application is None:
            raise ApplicationError(
                "INTERVIEW_NOT_FOUND",
                "投递记录不存在",
                status_code=404,
                details={"interview_id": interview_id},
            )
        return application

    def _commit(self, application: JobApplication) -> None:
        """提交投递变更，并将数据库失败转换为统一业务异常。
        
        参数:
            application: 已修改的投递记录，提交后需要重新加载。
        
        异常:
            ApplicationError: SQLAlchemy 无法提交事务时抛出。
        """
        try:
            queue_sync(self.session, application.id)
            self.session.commit()
            self.session.refresh(application)
        except SQLAlchemyError as exc:
            self.session.rollback()
            logger.exception("failed_to_update_interview interview_id=%s", application.id)
            raise ApplicationError(
                "DATABASE_WRITE_FAILED",
                "投递记录保存失败",
                status_code=500,
            ) from exc
