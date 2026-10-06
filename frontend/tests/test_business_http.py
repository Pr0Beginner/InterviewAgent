"""所有桌面业务操作均调用 HTTP 接口，服务错误不回退到演示数据。"""

import json
import unittest
import httpx

from client.api.hybrid_api import HybridApiClient, ApiRequestError
from client.api.mock_api import MockApiClient


class BusinessHttpTest(unittest.IsolatedAsyncioTestCase):
    async def test_business_requests_include_parameters_and_extensions(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={"ok": True})
        api = HybridApiClient("http://testserver/api", transport=httpx.MockTransport(handle))
        self.addCleanup(api.close)
        self.assertNotIsInstance(api, MockApiClient)
        operations = [
            ("recommend_jobs", {"cities": ["杭州"], "tech_stack": ["Java"], "page": 2, "extensions": {"future": 1}}, "POST", "/job-recommendations"),
            ("create_mock_interview", {"position_name": "Java", "interview_round": "一面"}, "POST", "/mock-interviews"),
            ("submit_mock_answer", {"session_id": "m1", "question_id": "q1", "answer": "回答"}, "POST", "/mock-interviews/m1/answers"),
            ("finish_mock_interview", {"session_id": "m1"}, "POST", "/mock-interviews/m1/finish"),
            ("get_mock_interview", {"session_id": "m1"}, "GET", "/mock-interviews/m1"),
            ("sync_email", {"limit": 10, "scope": "read"}, "POST", "/email/sync"),
            ("get_task", {"task_id": "mail1"}, "GET", "/tasks/mail1"),
        ]
        for name, params, method, path in operations:
            await api.invoke_async(name, **params)
            request = requests[-1]
            self.assertEqual(request.method, method)
            self.assertEqual(request.url.path, "/api" + path)
        first = json.loads(requests[0].content)
        self.assertEqual(first["page"], 2)
        self.assertEqual(first["extensions"], {"future": 1})
        email_body = json.loads(requests[5].content)
        self.assertEqual(email_body["scope"], "read")

    async def test_integrations_report_missing_configuration_without_fallback(self):
        api = HybridApiClient("http://testserver/api", transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"error": {"message": "请配置网易邮箱授权码。"}})))
        self.addCleanup(api.close)
        with self.assertRaisesRegex(ApiRequestError, "网易邮箱授权码"):
            await api.invoke_async("sync_email", limit=10, scope="unread")
