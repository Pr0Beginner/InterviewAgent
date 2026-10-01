import unittest

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from backend.app.db.base import Base
from backend.app.models import InterviewStatus


class ApplicationModelTest(unittest.TestCase):
    def test_business_tables_are_registered(self) -> None:
        self.assertEqual(
            set(Base.metadata.tables),
            {"job_applications", "application_status_history", "agent_operations", "email_receipts",
             "feishu_sync_items", "task_runs", "mock_interview_sessions"},
        )

    def test_application_fields_match_client_contract(self) -> None:
        columns = Base.metadata.tables["job_applications"].columns

        self.assertIn("company_name", columns)
        self.assertIn("position_name", columns)
        self.assertIn("base_location", columns)
        self.assertIn("current_status", columns)
        self.assertIn("interview_time", columns)
        self.assertIn("interview_end_time", columns)
        self.assertIn("job_url", columns)
        self.assertNotIn("next_action", columns)

    def test_status_values_are_exactly_the_supported_ten(self) -> None:
        self.assertEqual(
            [status.value for status in InterviewStatus],
            [
                "已投递",
                "简历筛选中",
                "笔试中",
                "待面试",
                "一面",
                "二面",
                "三面",
                "HR面",
                "Offer",
                "已结束",
            ],
        )

    def test_mysql_ddl_contains_status_check_and_cascade_foreign_key(self) -> None:
        application_ddl = str(
            CreateTable(Base.metadata.tables["job_applications"]).compile(
                dialect=mysql.dialect()
            )
        )
        history_ddl = str(
            CreateTable(Base.metadata.tables["application_status_history"]).compile(
                dialect=mysql.dialect()
            )
        )

        self.assertIn("CHECK", application_ddl)
        self.assertIn("Offer", application_ddl)
        self.assertIn("ON DELETE CASCADE", history_ddl)

        application_constraint_names = {
            constraint.name
            for constraint in Base.metadata.tables["job_applications"].constraints
        }
        history_constraint_names = {
            constraint.name
            for constraint in Base.metadata.tables["application_status_history"].constraints
        }
        self.assertIn("ck_job_applications_valid_status", application_constraint_names)
        self.assertIn(
            "ck_application_status_history_valid_status",
            history_constraint_names,
        )


if __name__ == "__main__":
    unittest.main()
