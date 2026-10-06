import unittest
import tempfile
from pathlib import Path

from client.api.mock_api import MockApiClient


class MockApiClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.api = MockApiClient()

    def test_list_and_update_interviews(self) -> None:
        response = self.api.list_interviews()
        self.assertGreater(response["total"], 0)
        interview_id = response["items"][0]["id"]
        updated = self.api.update_interview_status(interview_id, "二面")
        self.assertEqual(updated["current_status"], "二面")
        filtered = self.api.list_interviews(status="二面")
        self.assertTrue(any(item["id"] == interview_id for item in filtered["items"]))

    def test_update_all_interview_fields(self) -> None:
        interview_id = self.api.list_interviews()["items"][0]["id"]
        updated = self.api.update_interview(
            interview_id=interview_id,
            company_name="网易游戏",
            position_name="Java 服务端开发工程师",
            base_location="广州",
            current_status="三面",
            interview_time="2026-10-10 15:30",
            interview_end_time="2026-10-10 16:30",
            extensions={"source": "editable_table"},
        )
        self.assertEqual(updated["company_name"], "网易游戏")
        self.assertEqual(updated["interview_time"], "2026-10-10 15:30")
        self.assertEqual(updated["interview_end_time"], "2026-10-10 16:30")
        self.assertNotIn("next_action", updated)

    def test_interviews_are_sorted_by_start_time_descending(self) -> None:
        items = self.api.list_interviews(page=1, page_size=20)["items"]
        populated = [item["interview_time"] for item in items if item["interview_time"]]
        self.assertEqual(populated, sorted(populated, reverse=True))
        first_empty = next((index for index, item in enumerate(items) if not item["interview_time"]), len(items))
        self.assertTrue(all(not item["interview_time"] for item in items[first_empty:]))

    def test_agent_returns_openai_completion(self) -> None:
        response = self.api.create_chat_completion([
            {"role": "user", "content": "我目前有哪些面试？"},
        ])
        self.assertEqual(response["object"], "chat.completion")
        self.assertIn("进行中", response["choices"][0]["message"]["content"])

    def test_agent_message_uses_page_context_prompt(self) -> None:
        response = self.api.create_chat_completion(
            [{"role": "user", "content": "帮我看看"}],
            metadata={"page_context": "recommendations"},
        )
        self.assertIn("JD", response["choices"][0]["message"]["content"])

    def test_job_recommendations(self) -> None:
        result = self.api.recommend_jobs(
            cities=["上海"], keywords=["Java"]
        )
        self.assertGreater(result["total"], 0)
        self.assertTrue(all(item["base_location"] == "上海" for item in result["items"]))
        self.assertTrue(all(item["salary"] for item in result["items"]))

    def test_interview_and_job_pagination(self) -> None:
        interviews = self.api.list_interviews(page=2, page_size=5)
        self.assertEqual(interviews["page"], 2)
        self.assertEqual(interviews["total_pages"], 3)
        self.assertTrue(interviews["has_previous"])
        self.assertTrue(interviews["has_next"])
        self.assertEqual(interviews["summary"]["status_counts"]["Offer"], 1)

        jobs = self.api.recommend_jobs(
            cities=["上海", "杭州"],
            tech_stack=["Java"],
            keywords=["Java"],
            page=2,
            page_size=2,
        )
        self.assertEqual(jobs["page"], 2)
        self.assertEqual(len(jobs["items"]), 1)
        self.assertFalse(jobs["has_next"])

    def test_mock_interview_lifecycle(self) -> None:
        created = self.api.create_mock_interview(
            company_name="网易",
            position_name="Java 后端开发工程师",
            interview_round="一面",
        )
        answered = self.api.submit_mock_answer(
            created["session_id"], created["question_id"], "我负责订单服务的设计和性能优化。"
        )
        self.assertIn("score", answered)
        summary = self.api.finish_mock_interview(created["session_id"])
        self.assertGreater(summary["overall_score"], 0)

    def test_uploaded_resume_changes_first_mock_question(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            resume = Path(directory) / "resume.docx"
            resume.write_bytes(b"mock-docx-content")
            uploaded = self.api.upload_resume(str(resume))
        created = self.api.create_mock_interview(
            company_name=None,
            position_name="Java 后端开发工程师",
            interview_round="一面",
            resume_id=uploaded["id"],
        )
        self.assertIn("简历", created["question"])
        self.assertIn("项目", created["question"])


if __name__ == "__main__":
    unittest.main()
