"""本地业务接口和 Agent 上下文的契约测试。"""

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient

from backend.app.agent.context import ToolContextStore
from backend.app.api.routes.business import get_job_service, get_mock_service, get_resume_service
from backend.app.main import app
from backend.app.services.jobs import JobService
from backend.app.services.mock_interviews import MockInterviewService
from backend.app.services.resumes import ResumeService
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

    def test_resume_upload_endpoint_parses_docx(self):
        document = Document()
        document.add_paragraph("Java Spring Boot 项目经历：负责订单服务性能优化。")
        buffer = BytesIO()
        document.save(buffer)
        service = ResumeService(Path(self.temp.name) / "resumes", self.state)
        provider = FakeModel([{"question": "你在订单服务性能优化中做了哪些关键取舍？"}])
        app.dependency_overrides[get_resume_service] = lambda: service
        app.dependency_overrides[get_mock_service] = lambda: MockInterviewService(
            self.state, provider, resume_service=service
        )
        client = TestClient(app)
        try:
            response = client.post(
                "/api/mock-interviews/resumes",
                files={"file": ("resume.docx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )
            self.assertEqual(response.status_code, 201)
            payload = response.json()
            self.assertEqual(payload["file_name"], "resume.docx")
            self.assertGreater(payload["character_count"], 20)
            self.assertIn("Spring Boot", service.model_context(payload["id"])["text"])
            created = client.post("/api/mock-interviews", json={
                "position_name": "Java 后端",
                "interview_round": "一面",
                "resume_id": payload["id"],
            })
            self.assertEqual(created.status_code, 201)
            self.assertEqual(created.json()["resume"]["id"], payload["id"])
            self.assertIn("订单服务", provider.payloads[0]["context"]["resume"]["text"])
        finally:
            client.close()
            app.dependency_overrides.clear()

    def test_cached_jobs_do_not_open_external_source(self):
        class PreferenceMemory:
            def read_summary(self):
                return ""

        class Source:
            async def search(self, keywords, limit, cities=None, work_experience="应届生"):
                raise AssertionError("cached_only 不应访问外部页面")
        service = JobService(self.state, FakeModel([]), Source(), PreferenceMemory())
        from backend.app.schemas.business import JobSearchRequest
        result = __import__("asyncio").run(service.recommend(JobSearchRequest(
            cities=["杭州"], keywords=["Java 后端"], extensions={"cached_only": True},
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
