from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.models.enums import InterviewStatus
from backend.app.schemas.common import ExtensibleRequest


class InterviewRecord(BaseModel):
    """返回给桌面客户端的投递记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="投递记录 ID。")
    company_name: str = Field(description="公司名称。")
    position_name: str = Field(description="岗位名称。")
    base_location: str = Field(description="岗位工作地点。")
    current_status: InterviewStatus = Field(description="当前投递或面试状态。")
    interview_time: datetime | None = Field(description="笔试或面试开始时间；没有时为空。")
    interview_end_time: datetime | None = Field(description="笔试或面试结束时间；没有时为空。")
    job_url: str | None = Field(description="岗位原始链接；没有时为空。")
    updated_at: datetime = Field(description="记录最近更新时间。")


class InterviewSummary(BaseModel):
    """状态卡片统计，不受当前状态筛选条件影响。"""

    total: int = Field(description="文本筛选条件下的全部投递数量。")
    status_counts: dict[str, int] = Field(description="各投递状态分别对应的记录数量。")


class InterviewListResponse(BaseModel):
    """投递分页列表及状态汇总数量。"""

    items: list[InterviewRecord]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_previous: bool
    has_next: bool
    summary: InterviewSummary


class InterviewUpdateRequest(ExtensibleRequest):
    """用户保存表格单行时提交的可编辑字段。"""

    company_name: str = Field(min_length=1, max_length=255, description="公司名称。")
    position_name: str = Field(min_length=1, max_length=255, description="岗位名称。")
    base_location: str = Field(min_length=1, max_length=100, description="岗位工作地点。")
    current_status: InterviewStatus = Field(description="保存后的投递状态。")
    interview_time: datetime | None = Field(description="开始时间；清空时传 null。")
    interview_end_time: datetime | None = Field(description="结束时间；清空时传 null。")

    @model_validator(mode="after")
    def validate_time_range(self):
        """结束时间存在时必须晚于或等于开始时间。"""
        if self.interview_end_time is not None and self.interview_time is None:
            raise ValueError("设置结束时间前必须先设置开始时间")
        if (
            self.interview_time is not None
            and self.interview_end_time is not None
            and self.interview_end_time < self.interview_time
        ):
            raise ValueError("结束时间不能早于开始时间")
        return self


class InterviewUpdateResponse(InterviewRecord):
    """已保存的投递记录及其待同步到飞书的状态。"""

    feishu_sync_status: Literal["pending"] = "pending"


class InterviewStatusUpdateRequest(ExtensibleRequest):
    """供 Agent 或客户端仅修改投递状态的请求。"""

    target_status: InterviewStatus = Field(description="需要切换到的目标状态。")
    interview_time: datetime | None = Field(
        default=None,
        description="新的面试时间；省略时保持原值，显式传 null 时清空。",
    )
    note: str | None = Field(
        default=None,
        max_length=2000,
        description="写入状态历史的可选说明。",
    )


class InterviewStatusUpdateResponse(BaseModel):
    """投递状态变更结果。"""

    id: int
    previous_status: InterviewStatus
    current_status: InterviewStatus
    interview_time: datetime | None
    feishu_sync_status: Literal["pending"] = "pending"
    updated_at: datetime
