"""测试 HTTP 协议、连接器安全及 Agent 上下文持久化，不执行外部写入。"""

import asyncio
from html import escape
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.app.agent.context import ToolContextStore
from backend.app.agent.runtime import AgentRuntime
from backend.app.api.routes.business import get_mock_service, get_job_service
from backend.app.core.config import Settings
from backend.app.core.exceptions import ApplicationError
from backend.app.integrations.boss import BossJobSource, valid_job_url
from backend.app.integrations.feishu import FeishuClient, HEADERS, FIELDS
from backend.app.main import create_app
from backend.app.models import TaskRun
from backend.app.schemas.chat import ChatCompletionRequest
from backend.app.services.email_sync import EmailSyncService
from backend.app.services.jobs import JobService
from backend.app.services.mock_interviews import MockInterviewService
from backend.tests.test_agent_api import FakeProvider, native_chunk
from backend.tests.test_business import StoreTest, FakeModel


class BusinessApiTest(StoreTest):
    def setUp(self):
        super().setUp()
        self.app = create_app()
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_create_and_mock_session_endpoints(self):
        with patch("backend.app.api.routes.business.InterviewWorkflows", return_value=self.graphs):
            response = self.client.post("/api/interviews", json={"company_name": "测试公司", "position_name": "Java", "base_location": "杭州", "extensions": {"future": 1}})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["current_status"], "简历筛选中")
        provider = FakeModel([
            {"question": "介绍线程池参数。"},
            {"evaluation": "参数需要补充。", "score": 40, "question": "任务被拒绝有哪些策略？", "is_follow_up": True},
            {"overall_score": 40, "summary": "需要加强线程池。", "strengths": [], "weaknesses": ["概念不足"], "suggestions": ["阅读线程池实现"]},
        ])
        self.app.dependency_overrides[get_mock_service] = lambda: MockInterviewService(self.factory, provider)
        response = self.client.post("/api/mock-interviews", json={"position_name": "Java", "interview_round": "一面"})
        self.assertEqual(response.status_code, 201)
        created = response.json()
        path = "/api/mock-interviews/" + created["session_id"]
        answer = self.client.post(path + "/answers", json={"question_id": created["question_id"], "answer": "核心线程数、最大线程数。", "extensions": {}})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()["score"], 40)
        restored = self.client.get(path).json()
        self.assertEqual(len(restored["turns"]), 2)
        self.assertEqual(self.client.post(path + "/finish", json={}).json()["overall_score"], 40)
        self.assertEqual(self.client.get(path).json()["status"], "completed")
        self.assertEqual(self.client.get("/api/mock-interviews/missing").status_code, 404)

    def test_cached_jobs_do_not_open_browser_and_errors_are_not_demo_results(self):
        source = Mock()
        service = JobService(self.factory, FakeModel([]), source)
        self.app.dependency_overrides[get_job_service] = lambda: service
        response = self.client.post("/api/job-recommendations", json={"tech_stack": ["Java"], "extensions": {"cached_only": True}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])
        source.search.assert_not_called()
        self.assertEqual(self.client.get("/api/job-recommendations/missing").status_code, 404)
        self.assertEqual(self.client.post("/api/job-recommendations", json={"tech_stack": [], "page": 0}).status_code, 422)

    def test_interrupted_mail_task_can_be_retried_and_active_task_rejects_duplicates(self):
        with self.factory() as session:
            session.add(TaskRun(id="mail-old", kind="email", status="running", result={"_instance": "old", "updated": 1}))
            session.commit()
        with patch("backend.app.api.routes.business.get_session_factory", return_value=self.factory):
            task = self.client.get("/api/tasks/mail-old").json()
        self.assertEqual(task["status"], "failed")
        self.assertEqual(task["result"]["updated"], 1)
        self.assertNotIn("_instance", task["result"])
        service = EmailSyncService(self.factory, Mock(), FakeModel([]), self.graphs)
        service.create_task(5)
        with self.assertRaisesRegex(ApplicationError, "正在执行"):
            service.create_task(5)


class ConnectorTest(StoreTest):
    def test_feishu_cli_uses_configured_profile(self):
        """隐藏服务显式选择已授权 Profile，并关闭无关的升级通知。"""
        client = FeishuClient(Settings(
            _env_file=None, feishu_cli_path=sys.executable,
            feishu_cli_profile="authorized-profile",
        ))
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({
                "ok": True, "identity": "user", "data": {"value": 1},
            }), stderr="",
        )
        with patch("backend.app.integrations.feishu.subprocess.run", return_value=completed) as run:
            self.assertEqual(client._run(["docs", "+fetch"]), {"value": 1})
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"], "1")
        self.assertEqual(environment["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"], "1")
        command = run.call_args.args[0]
        self.assertEqual(command[1:3], ["--profile", "authorized-profile"])

    def test_feishu_cli_preserves_sanitized_error_details(self):
        """CLI 失败时返回操作、错误类型和缺失权限，不再统一误报登录问题。"""
        client = FeishuClient(Settings(_env_file=None, feishu_cli_path=sys.executable))
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=json.dumps({
                "ok": False,
                "identity": "user",
                "error": {
                    "type": "authorization",
                    "subtype": "missing_scope",
                    "code": 99991679,
                    "message": "missing scope",
                    "missing_scopes": ["sheets:spreadsheet:read"],
                    "hint": "grant the listed scope",
                    "access_token": "must-not-leak",
                },
            }),
        )
        with patch("backend.app.integrations.feishu.subprocess.run", return_value=completed):
            with self.assertRaises(ApplicationError) as context:
                client._run(["sheets", "+csv-get", "--spreadsheet-token", "private"])
        error = context.exception
        self.assertEqual(error.code, "FEISHU_REQUEST_FAILED")
        self.assertEqual(error.details["operation"], "sheets +csv-get")
        self.assertEqual(error.details["subtype"], "missing_scope")
        self.assertEqual(error.details["missing_scopes"], ["sheets:spreadsheet:read"])
        self.assertNotIn("access_token", error.details)

    def test_feishu_reads_managed_table_and_replaces_only_observed_block(self):
        record = {"id": 1, "company_name": "A & B", "position_name": "Java", "base_location": "杭州", "current_status": "一面"}
        xml = '<p id="personal">个人笔记</p><table id="managed"><thead><tr>' + ''.join(f'<th><p>{header}</p></th>' for header in HEADERS) + '</tr></thead><tbody><tr>' + ''.join(f'<td><p>{escape(str(record.get(key) or ""))}</p></td>' for key in FIELDS) + '</tr></tbody></table>'
        client = FeishuClient(Settings(_env_file=None, feishu_document_token="configured-document"))
        with patch.object(client, "_run", return_value={"document": {"content": xml, "revision_id": 8}}):
            current = client.read()
        self.assertEqual(current["block_id"], "managed")
        self.assertEqual(current["records"][0]["company_name"], "A & B")
        with patch.object(client, "_run", return_value={"result": "success"}) as run, patch.object(client, "read", return_value=current):
            client.write([record], current)
        args, content = run.call_args.args
        self.assertIn("block_replace", args)
        self.assertEqual(args[args.index("--block-id") + 1], "managed")
        self.assertNotIn("个人笔记", content)
        self.assertIn("A &amp; B", content)

    def test_boss_missing_login_and_external_urls_fail_closed(self):
        settings = Settings(_env_file=None, boss_profile_path=Path(self.temp.name) / "empty")
        with self.assertRaisesRegex(ApplicationError, "专用浏览器"):
            asyncio.run(BossJobSource(settings).search(["Java"], 1))
        self.assertTrue(valid_job_url("https://www.zhipin.com/job_detail/123.html"))
        for url in ["javascript:alert(1)", "https://www.zhipin.com.evil.test/job_detail/a.html", "https://www.zhipin.com/web/user/?job_detail=a.html"]:
            self.assertFalse(valid_job_url(url))

    def test_tool_context_is_persistent_and_isolated_by_tab(self):
        store = ToolContextStore(Path(self.temp.name) / "context.sqlite")
        key = store.key({"conversation_id": "one", "page_context": "mock_interview"})
        store.record(key, "start_mock_interview", {"session_id": "mock-123", "question_id": "q-123"})
        self.assertEqual(ToolContextStore(store.path).read(key)["mock_session_id"], "mock-123")
        self.assertEqual(store.read(store.key({"conversation_id": "one", "page_context": "applications"})), {})
        provider = FakeProvider([[native_chunk({"content": "请继续回答。"}, "stop")]])
        runtime = AgentRuntime(Settings(_env_file=None), provider=provider, context_store=store)
        asyncio.run(runtime.complete(ChatCompletionRequest(model="interview-assistant", messages=[{"role": "user", "content": "继续"}], metadata={"conversation_id": "one", "page_context": "mock_interview"})))
        self.assertIn("mock-123", provider.requests[0]["messages"][1]["content"])
        store.record(key, "finish_mock_interview", {})
        self.assertIsNone(store.read(key)["mock_session_id"])

    def test_agent_cannot_update_without_querying_record_first(self):
        provider = FakeProvider([
            [native_chunk({"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "update_interview_status", "arguments": '{"interview_id":1,"expected_status":"一面","target_status":"二面"}'}}]}, "tool_calls")],
            [native_chunk({"content": "需要先查询。"}, "stop")],
        ])
        executor = Mock()
        runtime = AgentRuntime(Settings(_env_file=None), provider, executor)
        asyncio.run(runtime.complete(ChatCompletionRequest(model="interview-assistant", messages=[{"role": "user", "content": "更新状态"}])))
        executor.assert_not_called()
        self.assertIn("本轮尚未查询", provider.requests[1]["messages"][-1]["content"])
