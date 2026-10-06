"""本地业务接口和 Agent 上下文的契约测试。"""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.agent.context import ToolContextStore
from backend.app.api.routes.business import get_job_service, get_mock_service
from backend.app.main import app
from backend.app.services.jobs import JobService
from backend.app.services.mock_interviews import MockInterviewService
from backend.app.storage.local import LocalStateStore
from backend.tests.test_business import FakeModel


class BusinessContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name)
        self.state = LocalStateStore(path / "runtime.json")
        self.context = ToolContextStore(path / "context.sqlite")

    def test_mock_session_endpoint_uses_local_state(self):
        provider = FakeModel([{"question": "介绍一个项目。"}])
        app.dependency_overrides[get_mock_service] = lambda: MockInterviewService(self.state, provider)
        client = TestClient(app)
        try:
            response = client.post("/api/mock-interviews", json={"position_name": "Java 后端", "interview_round": "一面"})
            self.assertEqual(response.status_code, 201)
            session_id = response.json()["session_id"]
            self.assertEqual(client.get(f"/api/mock-interviews/{session_id}").status_code, 200)
        finally:
            client.close()
            app.dependency_overrides.clear()

    def test_cached_jobs_do_not_open_external_source(self):
        class Source:
            async def search(self, keywords, limit):
                raise AssertionError("cached_only 不应访问外部页面")
        service = JobService(self.state, FakeModel([]), Source())
        from backend.app.schemas.business import JobSearchRequest
        result = __import__("asyncio").run(service.recommend(JobSearchRequest(
            cities=["杭州"], tech_stack=["Java"], extensions={"cached_only": True},
        )))
        self.assertEqual(result["items"], [])
        self.assertIn("尚无匹配结果", result["message"])

    def test_tool_context_is_persistent_and_isolated_by_page(self):
        applications = self.context.key({"conversation_id": "same", "page_context": "applications"})
        recommendations = self.context.key({"conversation_id": "same", "page_context": "recommendations"})
        self.context.record(applications, "start_mock_interview", {"session_id": "m1", "question_id": "q1"})
        restored = ToolContextStore(Path(self.temp.name) / "context.sqlite")
        self.assertEqual(restored.read(applications)["mock_session_id"], "m1")
        self.assertEqual(restored.read(recommendations), {})


if __name__ == "__main__":
    unittest.main()
