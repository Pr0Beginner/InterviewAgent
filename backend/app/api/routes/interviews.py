from __future__ import annotations

from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from backend.app.db.mysql import get_db_session
from backend.app.models.enums import InterviewStatus
from backend.app.schemas.interviews import (
    InterviewListResponse,
    InterviewRecord,
    InterviewStatusUpdateRequest,
    InterviewStatusUpdateResponse,
    InterviewSummary,
    InterviewUpdateRequest,
    InterviewUpdateResponse,
)
from backend.app.services.interviews import InterviewService

router = APIRouter(prefix="/interviews", tags=["Interviews"])


def get_interview_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> InterviewService:
    """使用请求级数据库会话创建面试业务服务。
    
    参数:
        session: FastAPI 通过依赖注入提供的 SQLAlchemy 会话。
    
    返回值:
        当前请求使用的业务服务实例。
    """
    return InterviewService(session)


@router.get("", response_model=InterviewListResponse)
def list_interviews(
    service: Annotated[InterviewService, Depends(get_interview_service)],
    company_name: Annotated[
        str | None, Query(max_length=255, description="按公司名称进行包含匹配。")
    ] = None,
    position_name: Annotated[
        str | None, Query(max_length=255, description="按岗位名称进行包含匹配。")
    ] = None,
    status: Annotated[
        InterviewStatus | None, Query(description="按系统支持的投递状态精确筛选。")
    ] = None,
    page: Annotated[int, Query(ge=1, description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=100, description="每页数量，范围 1 到 100。")
    ] = 20,
) -> InterviewListResponse:
    """返回筛选后的投递分页及状态卡片统计。
    
    参数:
        service: FastAPI 注入的面试业务服务。
        company_name: 可选的公司名称包含匹配条件。
        position_name: 可选的岗位名称包含匹配条件。
        status: 可选的精确状态筛选条件。
        page: 页码，从 1 开始。
        page_size: 每页最多返回的记录数。
    
    返回值:
        分页记录和各状态的统计数量。
    """
    result = service.list_interviews(
        company_name=company_name,
        position_name=position_name,
        status=status.value if status else None,
        page=page,
        page_size=page_size,
    )
    total_pages = max(1, ceil(result.total / page_size))
    return InterviewListResponse(
        items=[InterviewRecord.model_validate(item) for item in result.items],
        total=result.total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_previous=page > 1,
        has_next=page < total_pages,
        summary=InterviewSummary(
            total=result.summary_total,
            status_counts=result.status_counts,
        ),
    )


@router.patch("/{interview_id}", response_model=InterviewUpdateResponse)
def update_interview(
    request: InterviewUpdateRequest,
    service: Annotated[InterviewService, Depends(get_interview_service)],
    interview_id: Annotated[int, Path(ge=1, description="投递记录 ID。")],
) -> InterviewUpdateResponse:
    """保存桌面表格中一行记录的全部可编辑字段。
    
    参数:
        request: 已校验的行数据和可选扩展 Map。
        service: FastAPI 注入的面试业务服务。
        interview_id: URL 中的投递记录 ID。
    
    返回值:
        已保存的记录及其飞书同步状态。
    """
    application = service.update_interview(interview_id, request)
    return InterviewUpdateResponse.model_validate(application)


@router.patch("/{interview_id}/status", response_model=InterviewStatusUpdateResponse)
def update_interview_status(
    request: InterviewStatusUpdateRequest,
    service: Annotated[InterviewService, Depends(get_interview_service)],
    interview_id: Annotated[int, Path(ge=1, description="投递记录 ID。")],
) -> InterviewStatusUpdateResponse:
    """仅修改投递状态和可选的面试时间。
    
    参数:
        request: 目标状态、可选时间、备注和扩展 Map。
        service: FastAPI 注入的面试业务服务。
        interview_id: URL 中的投递记录 ID。
    
    返回值:
        变更前状态、当前状态和同步状态。
    """
    application, previous_status = service.update_status(interview_id, request)
    return InterviewStatusUpdateResponse(
        id=application.id,
        previous_status=InterviewStatus(previous_status),
        current_status=InterviewStatus(application.current_status),
        interview_time=application.interview_time,
        updated_at=application.updated_at,
    )
