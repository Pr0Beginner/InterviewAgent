"""业务写入、检查点、Skill 和邮件处理凭据的回归测试。"""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from backend.app.agent.workflows import InterviewWorkflows
from backend.app.core.exceptions import ApplicationError
from backend.app.db.base import Base
from backend.app.models import JobApplication, ApplicationStatusHistory, EmailReceipt, FeishuSyncItem, TaskRun
from backend.app.schemas.business import MockInterviewRequest, MockAnswerRequest, JobSearchRequest, EmailEvent
from backend.app.services.email_sync import EmailSyncService
from backend.app.services.jobs import JobService
from backend.app.services.mock_interviews import MockInterviewService
from backend.app.services.sync import sync_feishu


class FakeFeishu:
    def __init__(self, configured=False):
        self.records = []
        self.configured = configured
        self.writes = 0

    def read(self):
        return {"status": "success" if self.configured else "not_configured", "records": deepcopy(self.records), "block_id": "table", "revision_id": 1}

    def write(self, records, current):
        self.writes += 1
        self.records = deepcopy(records)


class FakeModel:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0

    def ensure_configured(self):
        pass

    async def structured(self, prompt, data, schema):
        self.calls += 1
        return schema.model_validate(next(self.results))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "business.sqlite"))
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        self.feishu = FakeFeishu()
        self.graphs = InterviewWorkflows(self.factory, Path(self.temp.name) / "states.sqlite", self.feishu)
        experience = patch("backend.app.integrations.feishu.FeishuClient.read_experience", return_value={"status": "not_configured", "sections": []})
        experience.start()
        self.addCleanup(experience.stop)

    def create(self):
        return self.graphs.mutate({"company_name": "测试公司", "position_name": "Java 后端", "base_location": "杭州", "current_status": "一面"}, "create-1", create=True)


class WorkflowsTest(StoreTest):
    def test_create_update_and_replay_have_one_audit_per_change(self):
        created = self.create()
        args = {"interview_id": created["id"], "expected_status": "一面", "target_status": "二面", "interview_time": "2026-10-03T14:00:00"}
        changed = self.graphs.mutate(args, "update-1")
        replay = self.graphs.mutate(args, "update-1")
        self.assertEqual(changed["current_status"], "二面")
        self.assertEqual(replay["id"], created["id"])
        self.assertEqual(changed["feishu_sync_status"], "pending")
        with self.factory() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ApplicationStatusHistory)), 2)
            self.assertEqual(session.get(FeishuSyncItem, created["id"]).status, "pending")
        self.assertTrue((Path(self.temp.name) / "states.sqlite").is_file())

    def test_stale_status_cannot_overwrite_recent_change(self):
        created = self.create()
        with self.assertRaisesRegex(ApplicationError, "重新查询"):
            self.graphs.mutate({"interview_id": created["id"], "expected_status": "笔试中", "target_status": "三面"}, "stale")
        with self.factory() as session:
            self.assertEqual(session.get(JobApplication, created["id"]).current_status, "一面")

    def test_agent_can_update_position_base_and_url_without_changing_status(self):
        """更新工具可局部修改整行字段，省略的状态和时间保持不变。"""
        created = self.create()
        changed = self.graphs.mutate({
            "interview_id": created["id"],
            "expected_status": "一面",
            "position_name": "AI应用研发",
            "base_location": "深圳",
            "job_url": "https://example.com/jobs/ai-application",
        }, "update-fields")
        self.assertEqual(changed["position_name"], "AI应用研发")
        self.assertEqual(changed["base_location"], "深圳")
        self.assertEqual(changed["job_url"], "https://example.com/jobs/ai-application")
        self.assertEqual(changed["current_status"], "一面")
        with self.factory() as session:
            row = session.get(JobApplication, created["id"])
            self.assertEqual(row.position_name, "AI应用研发")
            self.assertEqual(row.base_location, "深圳")
            self.assertEqual(session.scalar(select(func.count()).select_from(ApplicationStatusHistory)), 1)

    def test_query_graph_reports_remote_conflict_without_mutating(self):
        created = self.create()
        self.feishu.configured = True
        self.feishu.records = [{**created, "current_status": "三面"}]
        result = self.graphs.query({"company_name": "测试公司"})
        self.assertEqual(result["conflicts"][0]["feishu_status"], "三面")
        self.assertEqual(result["items"][0]["current_status"], "一面")
        self.assertEqual(self.feishu.writes, 0)

    def test_sync_completes_outbox_and_preserves_manual_remote_changes(self):
        created = self.create()
        self.feishu.configured = True
        result = sync_feishu(self.factory, self.feishu)
        self.assertEqual(result["success_count"], 1)
        with self.factory() as session:
            self.assertEqual(session.get(FeishuSyncItem, created["id"]).status, "success")
        self.feishu.records[0]["current_status"] = "Offer"
        with self.assertRaisesRegex(ApplicationError, "手动修改"):
            sync_feishu(self.factory, self.feishu)
        self.assertEqual(self.feishu.writes, 1)


class SkillServicesTest(StoreTest):
    def test_mock_interview_lifecycle_restore_and_duplicate_answer(self):
        provider = FakeModel([
            {"question": "解释 Java 的 volatile 语义。"},
            {"evaluation": "说明了可见性，缺少有序性。", "score": 65, "question": "volatile 能保证 i++ 原子性吗？", "is_follow_up": True},
            {"overall_score": 65, "summary": "基础概念尚需补全。", "strengths": ["知道可见性"], "weaknesses": ["遗漏有序性"], "suggestions": ["复习 happens-before"]},
        ])
        service = MockInterviewService(self.factory, provider)
        created = asyncio.run(service.create(MockInterviewRequest(company_name="网易", position_name="Java 后端", interview_round="一面")))
        request = MockAnswerRequest(question_id=created["question_id"], answer="保证线程间可见性。")
        first = asyncio.run(service.answer(created["session_id"], request))
        duplicate = asyncio.run(service.answer(created["session_id"], request))
        self.assertEqual(first, duplicate)
        self.assertEqual(provider.calls, 2)
        restored = MockInterviewService(self.factory, provider).get(created["session_id"])
        self.assertEqual(restored["turns"][0]["answer"], request.answer)
        report = asyncio.run(service.finish(created["session_id"]))
        self.assertEqual(asyncio.run(service.finish(created["session_id"])), report)
        self.assertEqual(provider.calls, 3)

    def test_empty_mock_interview_has_no_fabricated_score(self):
        provider = FakeModel([{"question": "介绍你的项目。"}])
        service = MockInterviewService(self.factory, provider)
        created = asyncio.run(service.create(MockInterviewRequest(position_name="Java", interview_round="一面")))
        self.assertEqual(asyncio.run(service.finish(created["session_id"]))["overall_score"], 0)
        self.assertEqual(provider.calls, 1)

    def test_job_pagination_reuses_snapshot_and_preserves_source_urls(self):
        class Source:
            calls = 0
            async def search(self, keywords, limit):
                self.calls += 1
                return [{"job_url": f"https://www.zhipin.com/job_detail/{index}.html", "job_description": "Java 后端，杭州，MySQL"} for index in range(3)]
        source = Source()
        provider = FakeModel([{"company_name": "测试公司", "position_name": "Java 后端", "base_location": "杭州", "match_score": 90 - index,
            "match_reasons": ["Java 匹配"], "risk_points": ["经验待核对"], "jd_summary": "Java 后端"} for index in range(3)])
        service = JobService(self.factory, provider, source)
        request = JobSearchRequest(cities=["杭州"], tech_stack=["Java"], page_size=2)
        page1 = asyncio.run(service.recommend(request))
        request.page = 2
        page2 = asyncio.run(service.recommend(request))
        self.assertEqual(len(page2["items"]), 1)
        self.assertEqual(source.calls, 1)
        self.assertEqual(provider.calls, 3)
        self.assertEqual(service.get(page1["items"][0]["id"])["job_url"], "https://www.zhipin.com/job_detail/0.html")


class MailServiceTest(StoreTest):
    def test_processed_mail_marking_retry_does_not_repeat_business_write(self):
        created = self.create()
        class Mailbox:
            marks = 0
            fail_mark = True
            def ensure_configured(self): pass
            @contextmanager
            def connect(self): yield self
            def unread(self, client, limit): return [{"uid": "42", "receipt_id": "a" * 64}]
            def fetch(self, client, uid): return {"subject": "二面邀请", "body": "测试公司邀请你参加Java 后端二面。"}
            def mark_read(self, client, uid):
                self.marks += 1
                if self.fail_mark:
                    raise ApplicationError("MARK_ERROR", "标记失败")
        mailbox = Mailbox()
        model = FakeModel([{"relevant": True, "company_name": "测试公司", "position_name": "Java 后端", "status": "二面",
                            "confidence": 0.99, "evidence": "二面邀请"}])
        service = EmailSyncService(self.factory, mailbox, model, self.graphs)
        task = service.create_task(10)
        service.run(task["task_id"], 10)
        mailbox.fail_mark = False
        task2 = service.create_task(10)
        service.run(task2["task_id"], 10)
        self.assertEqual(model.calls, 1)
        with self.factory() as session:
            self.assertEqual(session.get(JobApplication, created["id"]).current_status, "二面")
            self.assertEqual(session.get(TaskRun, task2["task_id"]).result["already_processed"], 1)
            self.assertEqual(set(EmailReceipt.__table__.columns.keys()), {"id", "outcome", "application_id", "processed_at"})

    def test_ambiguous_mail_is_not_marked_read(self):
        class Mailbox:
            def ensure_configured(self): pass
            @contextmanager
            def connect(self): yield self
            def unread(self, client, limit): return [{"uid": "43", "receipt_id": "b" * 64}]
            def fetch(self, client, uid): return {"subject": "面试", "body": "请参加面试"}
            def mark_read(self, client, uid): raise AssertionError("Ambiguous mail must stay unread")
        model = FakeModel([{"relevant": True, "confidence": 0.2, "evidence": "请参加面试"}])
        service = EmailSyncService(self.factory, Mailbox(), model, self.graphs)
        task = service.create_task(10)
        service.run(task["task_id"], 10)
        with self.factory() as session:
            row = session.get(TaskRun, task["task_id"])
            self.assertEqual(row.status, "partial_success")
            self.assertEqual(row.result["scope"], "unread")
            self.assertEqual(len(row.result["needs_review"]), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(EmailReceipt)), 0)


if __name__ == "__main__":
    unittest.main()
