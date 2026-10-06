import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api.routes.interviews import get_interview_service
from backend.app.main import app
from backend.app.services.interviews import InterviewService
from backend.app.storage.local import MarkdownInterviewStore


class InterviewsApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MarkdownInterviewStore(Path(self.temp.name) / "interviews.md")
        self.store.replace_all([
            {"id": 1, "company_name": "网易", "position_name": "Java 后端开发工程师", "base_location": "杭州", "current_status": "一面", "interview_time": datetime(2026, 10, 8, 14), "interview_end_time": datetime(2026, 10, 8, 15), "job_url": "https://example.com/netease", "created_at": datetime(2026, 9, 30), "updated_at": datetime(2026, 9, 30, 10, 20)},
            {"id": 2, "company_name": "字节跳动", "position_name": "后端开发工程师", "base_location": "上海", "current_status": "笔试中", "interview_time": None, "interview_end_time": None, "job_url": None, "created_at": datetime(2026, 9, 29), "updated_at": datetime(2026, 9, 29, 18, 10)},
            {"id": 3, "company_name": "美团", "position_name": "Java 服务端开发", "base_location": "北京", "current_status": "简历筛选中", "interview_time": datetime(2026, 10, 10, 10), "interview_end_time": datetime(2026, 10, 10, 11), "job_url": None, "created_at": datetime(2026, 9, 27), "updated_at": datetime(2026, 9, 27, 9, 30)},
        ])
        app.dependency_overrides[get_interview_service] = lambda: InterviewService(self.store)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(app.dependency_overrides.clear)

    def test_list_supports_pagination_filter_summary_and_time_order(self) -> None:
        response = self.client.get("/api/interviews", params={"page": 1, "page_size": 10})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["company_name"] for item in payload["items"]], ["美团", "网易", "字节跳动"])
        self.assertEqual(payload["summary"]["status_counts"]["笔试中"], 1)
        filtered = self.client.get("/api/interviews", params={"status": "一面", "page_size": 1}).json()
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["summary"]["total"], 3)

    def test_full_update_writes_local_file(self) -> None:
        response = self.client.patch("/api/interviews/1", json={
            "company_name": "网易游戏", "position_name": "Java 服务端开发工程师", "base_location": "广州",
            "current_status": "二面", "interview_time": "2026-10-10T15:30:00",
            "interview_end_time": "2026-10-10T16:30:00", "extensions": {"source": "editable_table"},
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["company_name"], "网易游戏")
        self.assertEqual(self.store.get(1).current_status, "二面")

    def test_status_update_keeps_omitted_time_and_unknown_returns_404(self) -> None:
        response = self.client.patch("/api/interviews/1/status", json={"target_status": "三面"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["interview_time"].startswith("2026-10-08T14:00"))
        missing = self.client.patch("/api/interviews/999/status", json={"target_status": "已结束"})
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
