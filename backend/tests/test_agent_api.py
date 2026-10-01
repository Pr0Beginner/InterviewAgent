"""接口协议和工具循环测试，不调用付费模型或用户数据库。"""

import json
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.agent.errors import AgentError
from backend.app.agent.runtime import AgentRuntime
from backend.app.agent.prompts import system_prompt
from backend.app.agent.tools import (
    BUSINESS_TOOLS,
    MUTATION_TOOLS,
    InterviewQuery,
    execute_tool,
    run_interview_query,
)
from backend.app.api.routes.chat import get_agent_runtime
from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.main import create_app
from backend.app.models import JobApplication


def native_chunk(delta: dict, finish=None, usage=None) -> dict:
    """构建模拟的模型响应块，用于断言协议边界行为。"""
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}], "usage": usage}


class FakeProvider:
    """输出固定结果的模型适配器，可检查其收到的请求。"""

    def __init__(self, rounds):
        self.rounds = iter(rounds)
        self.requests = []

    def ensure_configured(self):
        pass

    async def stream(self, messages, tools, **options):
        self.requests.append({"messages": list(messages), "tools": tools, **options})
        for event in next(self.rounds):
            if isinstance(event, Exception):
                raise event
            yield event


class AgentApiTest(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(_env_file=None, deepseek_api_key=None)
        self.app = create_app()
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def use_provider(self, provider, executor=execute_tool):
        self.app.dependency_overrides[get_agent_runtime] = lambda: AgentRuntime(
            self.settings, provider=provider, tool_executor=executor,
        )

    def request(self, **params):
        return self.client.post("/v1/chat/completions", json={
            "model": "interview-assistant",
            "messages": [{"role": "user", "content": "目前有哪些面试？"}],
            **params,
        })

    def test_nonstream_is_sdk_compatible_and_uses_page_prompt(self):
        provider = FakeProvider([[native_chunk({"content": "先从 Java 开始。", "reasoning_content": "private"}, "stop")]])
        self.use_provider(provider)
        response = self.request(metadata={"page_context": "mock_interview"}, extensions={"future": 1})
        self.assertEqual(response.status_code, 200)
        parsed = ChatCompletion.model_validate(response.json())
        self.assertEqual(parsed.choices[0].message.content, "先从 Java 开始。")
        self.assertNotIn("private", response.text)
        self.assertIn("一次只问一道题", provider.requests[0]["messages"][0]["content"])
        self.assertNotIn("extensions", provider.requests[0])

    def test_fragmented_tool_call_queries_real_records_then_streams_answer(self):
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        factory = sessionmaker(engine)
        with factory() as session:
            session.add(JobApplication(company_name="网易", position_name="Java 后端", base_location="杭州", current_status="一面"))
            session.commit()

        def executor(name, arguments):
            self.assertEqual(name, "query_interview_status")
            return run_interview_query(InterviewQuery.model_validate_json(arguments), factory)

        provider = FakeProvider([
            [native_chunk({"tool_calls": [{"index": 0, "id": "call-1", "function": {"name": "query_interview_status", "arguments": '{"company_name":'}}]}),
             native_chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"网易"}'}}]}, "tool_calls", {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7})],
            [native_chunk({"content": "网易"}), native_chunk({"content": "处于一面。"}, "stop", {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11})],
        ])
        self.use_provider(provider, executor)
        response = self.request(stream=True, stream_options={"include_usage": True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        frames = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(frames[-1], "[DONE]")
        chunks = [ChatCompletionChunk.model_validate(json.loads(frame)) for frame in frames[:-1]]
        content = "".join(choice.delta.content or "" for chunk in chunks for choice in chunk.choices)
        self.assertEqual(content, "网易处于一面。")
        self.assertEqual(len({chunk.id for chunk in chunks}), 1)
        self.assertEqual(chunks[-1].usage.total_tokens, 18)
        self.assertEqual(chunks[-1].choices, [])
        tool_result = json.loads(provider.requests[1]["messages"][-1]["content"])
        self.assertEqual(tool_result["items"][0]["current_status"], "一面")
        self.assertEqual(tool_result["feishu_sync_status"], "not_connected")

    def test_missing_key_returns_service_error_not_mock_reply(self):
        self.app.dependency_overrides[get_agent_runtime] = lambda: AgentRuntime(self.settings)
        response = self.request(stream=True)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "provider_not_configured")

    def test_validation_and_unknown_model_use_openai_error_envelope(self):
        self.use_provider(FakeProvider([]))
        for params in ({"messages": []}, {"metadata": {"page_context": "bogus"}}, {"tools": []}, {"stream_options": {"include_usage": True}}):
            with self.subTest(params=params):
                response = self.request(**params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["type"], "invalid_request_error")
        self.assertEqual(self.request(model="unknown").status_code, 404)
        self.assertEqual(self.client.get("/v1/models").json()["data"][0]["id"], "interview-assistant")

    def test_stream_failure_is_error_event_with_done(self):
        self.use_provider(FakeProvider([[native_chunk({"content": "部分"}), AgentError("模型暂不可用", "provider_error")]]))
        response = self.request(stream=True)
        self.assertIn('"code": "provider_error"', response.text)
        self.assertTrue(response.text.endswith("data: [DONE]\n\n"))

    def test_truncated_tool_arguments_never_execute(self):
        executor = Mock()
        self.use_provider(FakeProvider([[native_chunk({"tool_calls": [{"index": 0, "id": "call-1", "function": {"name": "query_interview_status", "arguments": "{"}}]}, "length")]]), executor)
        self.assertEqual(self.request().status_code, 502)
        executor.assert_not_called()

    def test_loop_limit_prevents_unbounded_model_requests(self):
        self.settings.agent_max_tool_rounds = 1
        event = native_chunk({"tool_calls": [{"index": 0, "id": "call-1", "function": {"name": "query_interview_status", "arguments": "{}"}}]}, "tool_calls")
        executor = Mock(return_value={"items": []})
        self.use_provider(FakeProvider([[event], [event]]), executor)
        self.assertEqual(self.request().status_code, 429)
        self.assertEqual(executor.call_count, 1)

    def test_tools_reject_unsafe_or_invalid_arguments(self):
        self.assertIn("error", execute_tool("update_interview", "{}"))
        self.assertIn("error", execute_tool("query_interview_status", '{"page_size":100000}'))
        self.assertIn("error", execute_tool("query_interview_status", '{"sql":"DROP TABLE jobs"}'))

    def test_general_update_tool_exposes_every_editable_business_field(self):
        """模型看到的是通用修改工具，而不是只能修改状态的专用工具。"""
        tools = {item["function"]["name"]: item["function"] for item in MUTATION_TOOLS}
        self.assertIn("update_interview", tools)
        self.assertNotIn("update_interview_status", tools)
        properties = tools["update_interview"]["parameters"]["properties"]
        self.assertTrue({
            "interview_id",
            "expected_status",
            "company_name",
            "position_name",
            "base_location",
            "target_status",
            "interview_time",
            "interview_end_time",
            "job_url",
        }.issubset(properties))
        self.assertNotIn("updated_at", properties)
        self.assertNotIn("created_at", properties)

    def test_email_tool_supports_all_scopes_and_hides_async_details(self):
        """Agent 使用等待完成的通用邮件工具，不把任务轮询机制暴露给用户。"""
        tools = {item["function"]["name"]: item["function"] for item in BUSINESS_TOOLS}
        self.assertIn("scan_emails", tools)
        self.assertNotIn("scan_unread_emails", tools)
        scope = tools["scan_emails"]["parameters"]["properties"]["scope"]
        self.assertEqual(scope["enum"], ["unread", "read", "all"])
        prompt = system_prompt("applications")
        self.assertIn("等待扫描结束", prompt)
        self.assertIn("不要向用户解释任务 ID", prompt)

    def test_email_scan_result_returns_to_conversation_in_same_request(self):
        """扫描完成统计应在同一轮工具循环中交给模型生成最终回复。"""
        provider = FakeProvider([
            [native_chunk({"tool_calls": [{
                "index": 0, "id": "mail-call", "function": {
                    "name": "scan_emails", "arguments": '{"limit":40,"scope":"read"}',
                },
            }]}, "tool_calls")],
            [native_chunk({"content": "已扫描 40 封已读邮件，更新 2 条投递记录。"}, "stop")],
        ])

        def executor(name, arguments):
            self.assertEqual(name, "scan_emails")
            self.assertEqual(json.loads(arguments), {"limit": 40, "scope": "read"})
            return {"task_id": "mail-test", "status": "completed", "result": {
                "scope": "read", "scanned": 40, "updated": 2, "ignored": 38,
                "already_processed": 0, "failed": 0, "needs_review": [],
            }, "error": None}

        self.use_provider(provider, executor)
        response = self.request()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["choices"][0]["message"]["content"],
                         "已扫描 40 封已读邮件，更新 2 条投递记录。")
        tool_result = json.loads(provider.requests[1]["messages"][-1]["content"])
        self.assertEqual(tool_result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
