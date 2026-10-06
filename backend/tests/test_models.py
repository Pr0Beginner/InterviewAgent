import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from backend.app.models import InterviewStatus
from backend.app.storage.local import MarkdownInterviewStore


class LocalStorageModelTest(unittest.TestCase):
    def test_status_values_are_exactly_the_supported_ten(self) -> None:
        self.assertEqual(
            [status.value for status in InterviewStatus],
            ["已投递", "简历筛选中", "笔试中", "待面试", "一面", "二面", "三面", "HR面", "Offer", "已结束"],
        )

    def test_markdown_roundtrip_preserves_business_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interviews.md"
            store = MarkdownInterviewStore(path)
            row = store.create({
                "company_name": "网易",
                "position_name": "Java 后端",
                "base_location": "杭州",
                "current_status": "一面",
                "interview_time": datetime(2026, 10, 8, 14, 0),
                "interview_end_time": datetime(2026, 10, 8, 15, 0),
                "job_url": "https://example.com/job",
            })
            loaded = MarkdownInterviewStore(path).get(row.id)
            self.assertEqual(loaded.company_name, "网易")
            self.assertEqual(loaded.interview_time, datetime(2026, 10, 8, 14, 0))
            self.assertIn("| ID | 公司 | 岗位 |", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
