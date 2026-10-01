"""经过校验的业务接口请求及模型生成的结构化输出。"""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl, model_validator

from backend.app.models.enums import InterviewStatus
from backend.app.schemas.common import ExtensibleRequest


class CreateInterview(ExtensibleRequest):
    company_name: str = Field(min_length=1, max_length=255, description="公司名称")
    position_name: str = Field(min_length=1, max_length=255, description="岗位名称")
    base_location: str = Field(min_length=1, max_length=100, description="Base 地；未知可填待确认")
    current_status: InterviewStatus = Field(default=InterviewStatus("简历筛选中"), description="当前投递状态")
    interview_time: datetime | None = Field(default=None, description="面试时间，中国本地时间 ISO 8601")
    job_url: HttpUrl | None = Field(default=None, description="原始岗位投递链接")


class ChangeInterview(ExtensibleRequest):
    interview_id: int = Field(ge=1, description="先查询取得的记录 ID")
    expected_status: InterviewStatus = Field(description="查询时状态，防止覆盖并发修改")
    company_name: str | None = Field(default=None, min_length=1, max_length=255, description="新的公司名称；省略保留原值")
    position_name: str | None = Field(default=None, min_length=1, max_length=255, description="新的岗位名称；省略保留原值")
    base_location: str | None = Field(default=None, min_length=1, max_length=100, description="新的 Base 地；省略保留原值")
    target_status: InterviewStatus | None = Field(default=None, description="新的投递状态；省略保留原值")
    interview_time: datetime | None = Field(default=None, description="省略保留原值，null 清空，中国本地时间 ISO 8601")
    job_url: HttpUrl | None = Field(default=None, description="新的岗位链接；省略保留原值，null 清空")
    note: str | None = Field(default=None, max_length=2000, description="写入状态历史的备注")

    @model_validator(mode="after")
    def validate_changes(self):
        """至少修改一个业务字段，且文本字段不能显式清空。"""
        editable = {"company_name", "position_name", "base_location", "target_status", "interview_time", "job_url"}
        changed = editable & self.model_fields_set
        if not changed:
            raise ValueError("至少提供一个需要修改的业务字段")
        for field_name in ("company_name", "position_name", "base_location", "target_status"):
            if field_name in changed and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} 不能为 null")
        return self


class EmailSyncRequest(ExtensibleRequest):
    limit: int = Field(default=50, ge=1, le=100, description="本次扫描邮件数量上限")
    scope: Literal["unread", "read", "all"] = Field(
        default="unread",
        description="扫描范围：unread 未读、read 已读、all 全部",
    )


class JobSearchRequest(ExtensibleRequest):
    cities: list[str] = Field(default_factory=list, max_length=10, description="目标城市；空列表表示不限制")
    tech_stack: list[str] = Field(min_length=1, max_length=30, description="用于匹配 JD 的技术栈")
    business_preferences: list[str] = Field(default_factory=list, max_length=20, description="偏好的业务方向")
    keywords: list[str] = Field(default_factory=list, max_length=20, description="岗位搜索词；省略则使用技术栈")
    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=10, ge=1, le=100, description="每页数量，最多 100")


class MockInterviewRequest(ExtensibleRequest):
    company_name: str | None = Field(default=None, max_length=255, description="目标公司；省略为通用面试")
    position_name: str = Field(min_length=1, max_length=255, description="目标岗位")
    interview_round: str = Field(min_length=1, max_length=100, description="目标面试轮次")
    interview_focus: list[str] = Field(default_factory=list, max_length=20, description="希望考察的知识方向")


class MockAnswerRequest(ExtensibleRequest):
    question_id: str = Field(min_length=1, max_length=64, description="当前待回答问题 ID")
    answer: str = Field(min_length=1, max_length=16000, description="用户实际回答")


class InterviewQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class AnswerEvaluation(BaseModel):
    evaluation: str = Field(min_length=1, max_length=6000)
    score: int = Field(ge=0, le=100)
    question: str = Field(min_length=1, max_length=4000)
    is_follow_up: bool


class InterviewReport(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=6000)
    strengths: list[str]
    weaknesses: list[str]
    suggestions: list[str]


class EmailEvent(BaseModel):
    relevant: bool
    company_name: str | None = None
    position_name: str | None = None
    status: InterviewStatus | None = None
    interview_time: datetime | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(default="", max_length=1000)


class JobAssessment(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    position_name: str = Field(min_length=1, max_length=255)
    base_location: str = Field(min_length=1, max_length=100)
    match_score: int = Field(ge=0, le=100)
    match_reasons: list[str]
    risk_points: list[str]
    jd_summary: str = Field(max_length=2000)
