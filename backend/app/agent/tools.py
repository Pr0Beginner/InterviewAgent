"""经过参数校验的 Agent 工具，与桌面接口复用同一套业务服务。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from backend.app.db.mysql import get_session_factory
from backend.app.models.enums import InterviewStatus
from backend.app.schemas.interviews import InterviewRecord
from backend.app.services.interviews import InterviewService
from backend.app.core.exceptions import ApplicationError
from backend.app.schemas.business import ChangeInterview, CreateInterview
from uuid import uuid4
import asyncio
from backend.app.schemas.business import JobSearchRequest, MockInterviewRequest, MockAnswerRequest, EmailSyncRequest
from backend.app.schemas.common import ExtensibleRequest


class InterviewQuery(BaseModel):
    """模型提取并经过校验的筛选条件，不接受原始 SQL。"""

    model_config = ConfigDict(extra="forbid")
    company_name: str | None = Field(default=None, max_length=255, description="公司名包含匹配")
    position_name: str | None = Field(default=None, max_length=255, description="岗位名包含匹配")
    status: InterviewStatus | None = Field(default=None, description="投递状态精确匹配；省略查询全部")
    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=20, ge=1, le=100, description="每页最多 100 条")


QUERY_TOOL = {
    "type": "function",
    "function": {
        "name": "query_interview_status",
        "description": "查询真实投递与面试记录、状态数量和面试时间，支持公司、岗位、状态筛选和分页。",
        "parameters": InterviewQuery.model_json_schema(),
    },
}

MUTATION_TOOLS = [
    {"type": "function", "function": {"name": "update_interview", "description": "通用修改任意一条投递或面试记录。可按需修改公司、岗位、Base、状态、面试时间和岗位链接；必须先查询并唯一定位记录，只传用户明确要求修改的字段。", "parameters": ChangeInterview.model_json_schema()}},
    {"type": "function", "function": {"name": "create_interview", "description": "用户明确要求添加投递时使用；公司、岗位、Base 和状态须来自用户，缺失时询问。", "parameters": CreateInterview.model_json_schema()}},
]


class SessionAnswer(MockAnswerRequest):
    session_id: str = Field(min_length=1, max_length=64)


class SessionFinish(ExtensibleRequest):
    session_id: str = Field(min_length=1, max_length=64)


class TaskQuery(BaseModel):
    task_id: str = Field(min_length=1, max_length=64)


BUSINESS_TOOL_MODELS = {
    "recommend_jobs": (JobSearchRequest, "根据城市、技术栈等搜索真实 BOSS 岗位并给出匹配度、JD 与投递链接"),
    "start_mock_interview": (MockInterviewRequest, "创建模拟面试会话并提出第一个问题"),
    "submit_mock_answer": (SessionAnswer, "评价模拟面试回答并动态追问；必须使用此前返回的会话与题目 ID"),
    "finish_mock_interview": (SessionFinish, "结束模拟面试并生成基于实际回答的总结"),
    "scan_emails": (EmailSyncRequest, "扫描网易邮箱并等待完成。scope 可选 unread、read、all；直接返回扫描统计和待核对邮件"),
    "get_task_status": (TaskQuery, "查询邮件扫描任务的进度、结果和需人工核对项"),
    "update_feishu_summary": (ExtensibleRequest, "用户要求时合并飞书进度、日期及 MySQL 投递；extensions.direction 为 both/pull/push，未注明轮次不猜测"),
    "read_interview_experience": (ExtensibleRequest, "读取当前配置中的个人面经，只返回 ZMY 部分，不读取其他人的面经"),
}
BUSINESS_TOOLS = [{"type": "function", "function": {"name": name, "description": description, "parameters": model.model_json_schema()}}
                  for name, (model, description) in BUSINESS_TOOL_MODELS.items()]


def run_interview_query(query: InterviewQuery, session_factory=None) -> dict[str, Any]:
    """使用短生命周期的数据库会话查询一页记录。
    
    参数:
        query: 已校验的筛选条件和分页范围。
        session_factory: 可选的 SQLAlchemy 会话工厂，供集成测试使用。
    
    返回值:
        可序列化为 JSON 的 MySQL 记录及数量；飞书数据由业务图另行合并。
    """
    factory = session_factory or get_session_factory()
    with factory() as session:
        result = InterviewService(session).list_interviews(
            company_name=query.company_name, position_name=query.position_name,
            status=query.status.value if query.status else None,
            page=query.page, page_size=query.page_size,
        )
        return {
            "items": [InterviewRecord.model_validate(row).model_dump(mode="json") for row in result.items],
            "total": result.total, "page": query.page, "page_size": query.page_size,
            "has_next": query.page * query.page_size < result.total,
            "summary": {"total": result.summary_total, "status_counts": result.status_counts},
            "source": "mysql", "feishu_sync_status": "not_connected",
        }


def execute_tool(name: str, arguments: str) -> dict[str, Any]:
    """校验模型发起的工具调用，返回受限结果或可安全展示的错误。
    
    参数:
        name: DeepSeek 返回的函数名。
        arguments: DeepSeek 返回的 JSON 格式函数参数。
    """
    try:
        from backend.app.agent.workflows import InterviewWorkflows
        if name == "query_interview_status":
            query = InterviewQuery.model_validate_json(arguments)
            return InterviewWorkflows().query(query.model_dump(mode="json"))
        if name in {"update_interview", "update_interview_status", "create_interview"}:
            model = CreateInterview if name == "create_interview" else ChangeInterview
            request = model.model_validate_json(arguments)
            return InterviewWorkflows().mutate(request.model_dump(mode="json", exclude_unset=True),
                uuid4().hex, create=name == "create_interview")
        if name in BUSINESS_TOOL_MODELS:
            request = BUSINESS_TOOL_MODELS[name][0].model_validate_json(arguments)
            return execute_business_tool(name, request)
        return {"error": "工具未接通，未执行任何操作。"}
    except ValidationError:
        return {"error": "工具参数不合法，请按照参数约束修正。"}
    except ApplicationError as exc:
        return {"error": exc.message, "code": exc.code}
    except SQLAlchemyError:
        return {"error": "数据库查询失败，无法确定当前状态。请检查数据库连接。"}


def execute_business_tool(name, request):
    """在工作线程中调用与图形界面接口相同的业务服务。"""
    from backend.app.services.mock_interviews import MockInterviewService
    from backend.app.services.jobs import JobService
    from backend.app.services.sync import sync_feishu
    from backend.app.services.email_sync import EmailSyncService, task_result
    from backend.app.models import TaskRun
    if name == "recommend_jobs":
        return asyncio.run(JobService().recommend(request))
    if name == "start_mock_interview":
        return asyncio.run(MockInterviewService().create(request))
    if name == "submit_mock_answer":
        return asyncio.run(MockInterviewService().answer(request.session_id, request))
    if name == "finish_mock_interview":
        return asyncio.run(MockInterviewService().finish(request.session_id))
    if name in {"scan_emails", "scan_unread_emails"}:
        service = EmailSyncService()
        task = service.create_task(request.limit, request.scope)
        service.run(task["task_id"], request.limit, request.scope)
        with get_session_factory()() as session:
            row = session.get(TaskRun, task["task_id"])
            return task_result(row)
    if name == "get_task_status":
        with get_session_factory()() as session:
            row = session.get(TaskRun, request.task_id)
            if row is None or row.kind != "email":
                return {"error": "任务不存在。"}
            result = task_result(row)
            session.commit()
            return result
    if name == "read_interview_experience":
        from backend.app.integrations.feishu import FeishuClient
        return FeishuClient().read_experience()
    return sync_feishu(direction=request.extensions.get("direction", "both"))
