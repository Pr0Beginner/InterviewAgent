from __future__ import annotations

from backend.app.schemas.interviews import InterviewStatusUpdateRequest, InterviewUpdateRequest
from backend.app.storage.local import LocalInterview, LocalInterviewPage, MarkdownInterviewStore


class InterviewService:
    """查询和更新本地 Markdown 中的投递进度。"""

    def __init__(self, store: MarkdownInterviewStore | None = None) -> None:
        self.store = store or MarkdownInterviewStore()

    def list_interviews(
        self,
        *,
        company_name: str | None,
        position_name: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> LocalInterviewPage:
        """返回筛选后的本地投递分页。"""
        return self.store.list_page(
            company_name=company_name,
            position_name=position_name,
            status=status,
            page=page,
            page_size=page_size,
        )

    def update_interview(
        self, interview_id: int, request: InterviewUpdateRequest
    ) -> LocalInterview:
        """保存桌面表格中一行的全部可编辑字段。"""
        application, _ = self.store.update(interview_id, {
            "company_name": request.company_name,
            "position_name": request.position_name,
            "base_location": request.base_location,
            "current_status": request.current_status.value,
            "interview_time": request.interview_time,
            "interview_end_time": request.interview_end_time,
        })
        return application

    def update_status(
        self, interview_id: int, request: InterviewStatusUpdateRequest
    ) -> tuple[LocalInterview, str]:
        """仅更新状态和调用方明确提供的开始时间。"""
        values = {"current_status": request.target_status.value}
        if "interview_time" in request.model_fields_set:
            values["interview_time"] = request.interview_time
        return self.store.update(interview_id, values)
