import unittest
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.db.mysql import get_db_session
from backend.app.main import app
from backend.app.models import ApplicationStatusHistory, JobApplication


class InterviewsApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.session_factory = sessionmaker(
            bind=cls.engine,
            class_=Session,
            expire_on_commit=False,
        )

        def override_session():
            with cls.session_factory() as session:
                yield session

        app.dependency_overrides[get_db_session] = override_session
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        cls.engine.dispose()

    def setUp(self) -> None:
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        with self.session_factory() as session:
            session.add_all(
                [
                    JobApplication(
                        company_name="网易",
                        position_name="Java 后端开发工程师",
                        base_location="杭州",
                        current_status="一面",
                        interview_time=datetime(2026, 10, 8, 14, 0),
                        job_url="https://example.com/netease",
                        updated_at=datetime(2026, 9, 30, 10, 20),
                    ),
                    JobApplication(
                        company_name="字节跳动",
                        position_name="后端开发工程师",
                        base_location="上海",
                        current_status="笔试中",
                        interview_time=None,
                        job_url="https://example.com/bytedance",
                        updated_at=datetime(2026, 9, 29, 18, 10),
                    ),
                    JobApplication(
                        company_name="美团",
                        position_name="Java 服务端开发",
                        base_location="北京",
                        current_status="简历筛选中",
                        interview_time=None,
                        job_url="https://example.com/meituan",
                        updated_at=datetime(2026, 9, 27, 9, 30),
                    ),
                ]
            )
            session.commit()

    def test_list_interviews_supports_pagination_filter_and_summary(self) -> None:
        response = self.client.get(
            "/api/interviews",
            params={"status": "一面", "page": 1, "page_size": 1},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["company_name"], "网易")
        self.assertEqual(payload["summary"]["total"], 3)
        self.assertEqual(payload["summary"]["status_counts"]["笔试中"], 1)
        self.assertEqual(payload["summary"]["status_counts"]["Offer"], 0)

    def test_full_update_accepts_extensions_and_writes_status_history(self) -> None:
        interview_id = self._application_id("网易")
        response = self.client.patch(
            f"/api/interviews/{interview_id}",
            json={
                "company_name": "网易游戏",
                "position_name": "Java 服务端开发工程师",
                "base_location": "广州",
                "current_status": "二面",
                "interview_time": "2026-10-10T15:30:00",
                "updated_at": "2026-09-30T16:00:00",
                "extensions": {"source": "editable_table"},
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["company_name"], "网易游戏")
        self.assertEqual(payload["current_status"], "二面")
        self.assertEqual(payload["feishu_sync_status"], "pending")
        self.assertNotIn("extensions", payload)

        with self.session_factory() as session:
            history = session.scalar(
                select(ApplicationStatusHistory).where(
                    ApplicationStatusHistory.application_id == interview_id
                )
            )
            self.assertIsNotNone(history)
            self.assertEqual(history.previous_status, "一面")
            self.assertEqual(history.current_status, "二面")

    def test_status_update_keeps_time_when_parameter_is_omitted(self) -> None:
        interview_id = self._application_id("网易")
        response = self.client.patch(
            f"/api/interviews/{interview_id}/status",
            json={
                "target_status": "三面",
                "note": "用户通过 Agent 更新",
                "extensions": {"conversation_id": "conv-test"},
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["previous_status"], "一面")
        self.assertEqual(payload["current_status"], "三面")
        self.assertTrue(payload["interview_time"].startswith("2026-10-08T14:00"))

    def test_unknown_record_returns_standard_error(self) -> None:
        response = self.client.patch(
            "/api/interviews/999/status",
            json={"target_status": "已结束"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "INTERVIEW_NOT_FOUND")

    def test_invalid_status_returns_validation_error(self) -> None:
        response = self.client.get("/api/interviews", params={"status": "待投递"})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def _application_id(self, company_name: str) -> int:
        with self.session_factory() as session:
            interview_id = session.scalar(
                select(JobApplication.id).where(
                    JobApplication.company_name == company_name
                )
            )
            assert interview_id is not None
            return interview_id


if __name__ == "__main__":
    unittest.main()
