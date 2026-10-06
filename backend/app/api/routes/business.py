"""投递新增、外部集成、岗位推荐和模拟面试接口。"""

import asyncio
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile

from backend.app.agent.workflows import InterviewWorkflows
from backend.app.schemas.business import (
    CreateInterview,
    EmailCandidateCreateRequest,
    EmailSyncRequest,
    JobSearchRequest,
    MockInterviewRequest,
    MockAnswerRequest,
)
from backend.app.schemas.common import ExtensibleRequest
from backend.app.services.email_sync import EmailSyncService
from backend.app.services.jobs import JobService
from backend.app.services.mock_interviews import MockInterviewService
from backend.app.services.resumes import ResumeService

router = APIRouter(tags=["Business"])


def get_mock_service():
    """创建模拟面试服务，其依赖可在测试中替换。"""
    return MockInterviewService()


def get_resume_service():
    """创建本地简历解析服务，其依赖可在测试中替换。"""
    return ResumeService()


def get_job_service():
    """创建使用真实岗位来源的推荐服务。"""
    return JobService()


@router.post("/interviews", status_code=201)
def create_interview(request: CreateInterview):
    """根据明确的公司、岗位、工作地点和状态创建投递记录。"""
    return InterviewWorkflows().mutate(request.model_dump(mode="json", exclude_unset=True), uuid4().hex, create=True)


@router.post("/email/sync", status_code=202)
def synchronize_email(request: EmailSyncRequest, background_tasks: BackgroundTasks):
    """接收邮件扫描请求；范围可选未读、已读或全部。"""
    service = EmailSyncService()
    result = service.create_task(request.limit, request.scope)
    background_tasks.add_task(service.run, result["task_id"], request.limit, request.scope)
    return result


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    """返回本地任务状态、统计数量和可安全展示的错误说明。"""
    return EmailSyncService().get_task(task_id)


@router.post("/email/candidates/create")
def create_email_candidates(request: EmailCandidateCreateRequest):
    """根据前端明确勾选的邮件候选项创建本地投递记录。"""
    return EmailSyncService().create_candidates(request.candidate_ids)


@router.post("/job-recommendations")
async def recommend_jobs(request: JobSearchRequest, service: Annotated[JobService, Depends(get_job_service)]):
    """读取真实岗位页面、评估匹配度，并返回缓存结果中的一页。"""
    return await service.recommend(request)


@router.get("/job-recommendations/{recommendation_id}")
def get_job(recommendation_id: str, service: Annotated[JobService, Depends(get_job_service)]):
    """根据推荐记录 ID 返回已保存的 JD、评分和来源链接。"""
    return service.get(recommendation_id)


@router.post("/mock-interviews/resumes", status_code=201)
async def upload_mock_resume(
    file: Annotated[UploadFile, File(...)],
    service: Annotated[ResumeService, Depends(get_resume_service)],
):
    """解析 PDF/DOCX 简历并把提取后的文本保存到本地。"""
    data = await file.read(ResumeService.MAX_BYTES + 1)
    await file.close()
    return await asyncio.to_thread(service.save, file.filename, data)


@router.post("/mock-interviews", status_code=201)
async def create_mock(request: MockInterviewRequest, service: Annotated[MockInterviewService, Depends(get_mock_service)]):
    """根据目标公司和岗位，使用 Skill 开始模拟面试。"""
    return await service.create(request)


@router.get("/mock-interviews/{session_id}")
def get_mock(session_id: str, service: Annotated[MockInterviewService, Depends(get_mock_service)]):
    """恢复已保存的面试上下文、问答记录和总结。"""
    return service.get(session_id)


@router.post("/mock-interviews/{session_id}/answers")
async def submit_answer(session_id: str, request: MockAnswerRequest, service: Annotated[MockInterviewService, Depends(get_mock_service)]):
    """评价当前题目的回答，并选择追问或下一题。"""
    return await service.answer(session_id, request)


@router.post("/mock-interviews/{session_id}/finish")
async def finish_mock(session_id: str, request: ExtensibleRequest, service: Annotated[MockInterviewService, Depends(get_mock_service)]):
    """结束已保存的模拟面试，并持久化基于实际回答的评价。"""
    return await service.finish(session_id)
