"""使用临时本地文件进行付费模型冒烟测试，不操作用户记录。"""

import asyncio
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from backend.app.agent.context import ToolContextStore
from backend.app.agent.provider import DeepSeekProvider
from backend.app.agent.runtime import AgentRuntime
from backend.app.agent.workflows import InterviewWorkflows
from backend.app.core.config import get_settings
from backend.app.schemas.business import EmailEvent, JobAssessment, MockAnswerRequest, MockInterviewRequest
from backend.app.schemas.chat import ChatCompletionRequest
from backend.app.services.email_sync import EMAIL_INSTRUCTIONS
from backend.app.services.jobs import SKILL as JOB_SKILL
from backend.app.services.mock_interviews import MockInterviewService
from backend.app.storage.local import LocalStateStore, MarkdownInterviewStore


async def checks(graphs, store, state_store, context_path):
    """测试真实 DeepSeek 工具调用、Skill 输出和邮件 JSON 提取。"""
    settings = get_settings()
    calls = []

    def executor(name, arguments):
        args = json.loads(arguments)
        calls.append(name)
        if name == "query_interview_status":
            return graphs.query(args)
        if name in {"create_interview", "update_interview"}:
            return graphs.mutate(args, uuid4().hex, create=name == "create_interview")
        return {"error": "此测试只允许临时本地文件的查询、创建和修改。"}

    runtime = AgentRuntime(settings, tool_executor=executor, context_store=ToolContextStore(context_path))
    history = []
    for name, message in [
        ("create", "请新增一条投递记录：公司是测试公司，岗位是Java后端，Base杭州，当前状态一面。"),
        ("update", "请把测试公司的Java后端岗位状态更新为二面，时间是2026年10月8日14:00。"),
        ("query", "请查询测试公司现在的状态和面试时间。"),
    ]:
        history.append({"role": "user", "content": message})
        result = await runtime.complete(ChatCompletionRequest(
            model=settings.agent_model_name,
            messages=history,
            metadata={"page_context": "applications", "conversation_id": "isolated-live-smoke"},
            max_tokens=1200,
        ))
        answer = result["choices"][0]["message"]["content"]
        history.append({"role": "assistant", "content": answer})
        print(json.dumps({"check": name, "reply": answer}, ensure_ascii=False), flush=True)
    row = store.all()[0]
    assert row.current_status == "二面" and row.interview_time.hour == 14
    assert {"create_interview", "update_interview", "query_interview_status"}.issubset(calls)

    provider = DeepSeekProvider(settings)
    mock = MockInterviewService(state_store, provider, max_questions=2)
    created = await mock.create(MockInterviewRequest(company_name="网易", position_name="Java后端", interview_round="一面", interview_focus=["Java并发"]))
    answer = await mock.answer(created["session_id"], MockAnswerRequest(question_id=created["question_id"], answer="volatile 保证可见性和一定的有序性，但不能保证复合操作的原子性。"))
    report = await mock.finish(created["session_id"])
    assert mock.get(created["session_id"])["report"] == report
    print(json.dumps({"check": "mock_interview", "question": created["question"], "score": answer["score"], "report_saved": True}, ensure_ascii=False), flush=True)

    event = await provider.structured(EMAIL_INSTRUCTIONS, {"subject": "测试公司二面邀请", "body": "测试公司邀请你参加Java后端岗位二面，时间2026年10月8日14:00。"}, EmailEvent)
    assert event.relevant and event.status.value == "二面" and event.company_name == "测试公司"
    job = await provider.structured(JOB_SKILL, {"profile": {"cities": ["杭州"], "tech_stack": ["Java", "MySQL"]}, "source": {"job_description": "合成测试JD：测试公司，Java后端校招工程师，杭州。"}}, JobAssessment)
    assert 0 <= job.match_score <= 100


def main():
    """创建并释放独立本地存储；仅 DeepSeek 请求访问进程外服务。"""
    with tempfile.TemporaryDirectory(prefix="ia-live-smoke-") as directory:
        path = Path(directory)
        store = MarkdownInterviewStore(path / "interviews.md")
        state_store = LocalStateStore(path / "runtime.json")
        graphs = InterviewWorkflows(store, path / "graph.sqlite", state_store)
        asyncio.run(checks(graphs, store, state_store, path / "graph.sqlite"))


if __name__ == "__main__":
    main()
