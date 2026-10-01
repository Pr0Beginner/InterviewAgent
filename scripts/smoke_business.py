"""使用临时数据库进行付费模型冒烟测试，不操作用户记录，需手动执行。"""

import asyncio
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.agent.context import ToolContextStore
from backend.app.agent.provider import DeepSeekProvider
from backend.app.agent.runtime import AgentRuntime
from backend.app.agent.workflows import InterviewWorkflows
from backend.app.core.config import Settings, get_settings
from backend.app.db.base import Base
from backend.app.integrations.feishu import FeishuClient
from backend.app.models import JobApplication
from backend.app.schemas.chat import ChatCompletionRequest
from backend.app.schemas.business import MockInterviewRequest, MockAnswerRequest, EmailEvent, JobAssessment
from backend.app.services.email_sync import EMAIL_INSTRUCTIONS
from backend.app.services.jobs import SKILL as JOB_SKILL
from backend.app.services.mock_interviews import MockInterviewService


async def checks(factory, graphs, context_path):
    """测试真实 DeepSeek 工具调用、Skill 输出和邮件 JSON 提取。"""
    settings = get_settings()
    calls = []

    def executor(name, arguments):
        """仅允许调用测试数据库的三个本地工具，禁止所有外部修改。"""
        args = json.loads(arguments)
        calls.append(name)
        if name == "query_interview_status":
            return graphs.query(args)
        if name in {"create_interview", "update_interview_status"}:
            return graphs.mutate(args, uuid4().hex, create=name == "create_interview")
        return {"error": "此测试只允许测试库的查询、创建和状态修改。"}

    runtime = AgentRuntime(settings, tool_executor=executor, context_store=ToolContextStore(context_path))
    history = []
    for name, message in [
        ("create", "请新增一条投递记录：公司是测试公司，岗位是Java后端，Base杭州，当前状态一面。"),
        ("update", "请把测试公司的Java后端岗位状态更新为二面，时间是2026年10月8日14:00。"),
        ("query", "请查询测试公司现在的状态和面试时间。"),
    ]:
        history.append({"role": "user", "content": message})
        result = await runtime.complete(ChatCompletionRequest(model=settings.agent_model_name, messages=history,
            metadata={"page_context": "applications", "conversation_id": "isolated-live-smoke"}, max_tokens=1200))
        answer = result["choices"][0]["message"]["content"]
        history.append({"role": "assistant", "content": answer})
        print(json.dumps({"check": name, "reply": answer}, ensure_ascii=False), flush=True)
    with factory() as session:
        row = session.scalar(select(JobApplication))
        assert row is not None and row.current_status == "二面" and row.interview_time.hour == 14
    assert {"create_interview", "update_interview_status", "query_interview_status"}.issubset(calls)

    provider = DeepSeekProvider(settings)
    mock = MockInterviewService(factory, provider, max_questions=2, feishu=FeishuClient(Settings(_env_file=None)))
    created = await mock.create(MockInterviewRequest(company_name="网易", position_name="Java后端", interview_round="一面", interview_focus=["Java并发"]))
    answer = await mock.answer(created["session_id"], MockAnswerRequest(question_id=created["question_id"], answer="volatile 保证可见性和一定的有序性，但不能保证复合操作的原子性，比如 i++ 需要锁或者原子类。"))
    report = await mock.finish(created["session_id"])
    assert mock.get(created["session_id"])["report"] == report
    print(json.dumps({"check": "mock_interview", "question": created["question"], "score": answer["score"], "report_saved": True}, ensure_ascii=False), flush=True)

    event = await provider.structured(EMAIL_INSTRUCTIONS, {"subject": "测试公司二面邀请", "body": "测试公司邀请你参加Java后端岗位二面，时间2026年10月8日14:00。"}, EmailEvent)
    assert event.relevant and event.status.value == "二面" and event.company_name == "测试公司"
    print(json.dumps({"check": "email_extraction", "status": event.status.value, "no_mailbox_access": True}, ensure_ascii=False), flush=True)
    job = await provider.structured(JOB_SKILL, {"profile": {"cities": ["杭州"], "tech_stack": ["Java", "MySQL"]},
        "source": {"job_description": "合成测试JD，不是真实招聘：测试公司，Java后端校招工程师，杭州。要求熟悉Java、Spring Boot、MySQL和Redis。"}}, JobAssessment)
    assert 0 <= job.match_score <= 100 and job.company_name == "测试公司"
    print(json.dumps({"check": "job_assessment", "score": job.match_score, "source": "synthetic_test_only"}, ensure_ascii=False), flush=True)


def main():
    """创建并释放独立测试存储；仅 DeepSeek 请求会访问进程外的服务。"""
    with tempfile.TemporaryDirectory(prefix="ia-live-smoke-") as directory:
        path = Path(directory)
        engine = create_engine("sqlite:///" + str(path / "business.sqlite"))
        try:
            Base.metadata.create_all(engine)
            factory = sessionmaker(engine, expire_on_commit=False)
            graphs = InterviewWorkflows(factory, path / "graph.sqlite", FeishuClient(Settings(_env_file=None, feishu_document_token=None)))
            asyncio.run(checks(factory, graphs, path / "graph.sqlite"))
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
