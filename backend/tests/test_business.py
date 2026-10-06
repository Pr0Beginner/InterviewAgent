"""本地业务文件、Skill 服务和邮件去重的回归测试。"""

import asyncio
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from backend.app.agent.workflows import InterviewWorkflows
from backend.app.core.exceptions import ApplicationError
from backend.app.schemas.business import EmailEvent, JobSearchRequest, MockAnswerRequest, MockInterviewRequest
from backend.app.services.email_sync import EmailSyncService
from backend.app.services.jobs import JobService
from backend.app.services.mock_interviews import MockInterviewService
from backend.app.storage.local import LocalStateStore, MarkdownInterviewStore


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
        path = Path(self.temp.name)
        self.store = MarkdownInterviewStore(path / "interviews.md")
        self.state = LocalStateStore(path / "runtime.json")
        self.graphs = InterviewWorkflows(self.store, path / "graph.sqlite", self.state)

    def create(self):
        return self.graphs.mutate({
            "company_name": "测试公司", "position_name": "Java 后端",
            "base_location": "杭州", "current_status": "一面",
        }, "create-1", create=True)


class WorkflowsTest(StoreTest):
    def test_create_update_query_and_replay_use_local_files(self):
        created = self.create()
        args = {"interview_id": created["id"], "expected_status": "一面", "target_status": "二面", "interview_time": "2026-10-03T14:00:00"}
        changed = self.graphs.mutate(args, "update-1")
        replay = self.graphs.mutate(args, "update-1")
        self.assertEqual(changed["current_status"], "二面")
        self.assertEqual(replay, changed)
        self.assertEqual(self.graphs.query({"company_name": "测试公司"})["source"], "local_markdown")
        self.assertTrue((Path(self.temp.name) / "interviews.md").is_file())

    def test_stale_status_cannot_overwrite_recent_change(self):
        created = self.create()
        with self.assertRaisesRegex(ApplicationError, "重新查询"):
            self.graphs.mutate({"interview_id": created["id"], "expected_status": "笔试中", "target_status": "三面"}, "stale")
        self.assertEqual(self.store.get(created["id"]).current_status, "一面")

    def test_agent_can_update_any_record_field(self):
        created = self.create()
        changed = self.graphs.mutate({
            "interview_id": created["id"], "expected_status": "一面",
            "position_name": "AI应用研发", "base_location": "深圳",
            "job_url": "https://example.com/jobs/ai-application",
        }, "update-fields")
        self.assertEqual(changed["position_name"], "AI应用研发")
        self.assertEqual(changed["base_location"], "深圳")
        self.assertEqual(self.store.get(created["id"]).job_url, "https://example.com/jobs/ai-application")


class SkillServicesTest(StoreTest):
    def test_mock_interview_lifecycle_persists_in_json(self):
        provider = FakeModel([
            {"question": "解释 Java 的 volatile 语义。"},
            {"evaluation": "说明了可见性，缺少有序性。", "score": 65, "question": "volatile 能保证 i++ 原子性吗？", "is_follow_up": True},
            {"overall_score": 65, "summary": "基础概念尚需补全。", "strengths": ["知道可见性"], "weaknesses": ["遗漏有序性"], "suggestions": ["复习 happens-before"]},
        ])
        service = MockInterviewService(self.state, provider)
        created = asyncio.run(service.create(MockInterviewRequest(company_name="网易", position_name="Java 后端", interview_round="一面")))
        request = MockAnswerRequest(question_id=created["question_id"], answer="保证线程间可见性。")
        first = asyncio.run(service.answer(created["session_id"], request))
        self.assertEqual(asyncio.run(service.answer(created["session_id"], request)), first)
        self.assertIn("answer", MockInterviewService(self.state, provider).get(created["session_id"])["turns"][0])
        report = asyncio.run(service.finish(created["session_id"]))
        self.assertEqual(asyncio.run(service.finish(created["session_id"])), report)

    def test_job_pagination_reuses_local_snapshot(self):
        class Source:
            calls = 0
            async def search(self, keywords, limit):
                self.calls += 1
                return [{"job_url": f"https://www.zhipin.com/job_detail/{index}.html", "job_description": "Java 后端，杭州，MySQL"} for index in range(3)]
        source = Source()
        provider = FakeModel([{"company_name": "测试公司", "position_name": "Java 后端", "base_location": "杭州", "match_score": 90 - index, "match_reasons": ["Java 匹配"], "risk_points": ["经验待核对"], "jd_summary": "Java 后端"} for index in range(3)])
        service = JobService(self.state, provider, source)
        request = JobSearchRequest(cities=["杭州"], tech_stack=["Java"], page_size=2)
        page1 = asyncio.run(service.recommend(request))
        request.page = 2
        page2 = asyncio.run(service.recommend(request))
        self.assertEqual(len(page2["items"]), 1)
        self.assertEqual(source.calls, 1)
        self.assertEqual(service.get(page1["items"][0]["id"])["job_url"], "https://www.zhipin.com/job_detail/0.html")


class MailServiceTest(StoreTest):
    def test_processed_mail_retry_does_not_repeat_business_write(self):
        created = self.create()

        class Mailbox:
            marks = 0
            fail_mark = True
            def ensure_configured(self): pass
            @contextmanager
            def connect(self): yield self
            def unread(self, client, limit): return [{"uid": "42", "receipt_id": "a" * 64}]
            def fetch(self, client, uid): return {"subject": "测试公司二面邀请", "body": "测试公司 Java 后端二面邀请，时间 2026-10-08 14:00。"}
            def mark_read(self, client, uid):
                self.marks += 1
                if self.fail_mark:
                    self.fail_mark = False
                    raise RuntimeError("mark failed")

        provider = FakeModel([EmailEvent(relevant=True, confidence=1, company_name="测试公司", position_name="Java 后端", status="二面", interview_time="2026-10-08T14:00:00", evidence="测试公司 Java 后端二面邀请").model_dump()])
        mailbox = Mailbox()
        service = EmailSyncService(self.state, self.store, mailbox, provider, self.graphs)
        first = service.create_task(1)
        service.run(first["task_id"], 1)
        second = service.create_task(1)
        service.run(second["task_id"], 1)
        self.assertEqual(self.store.get(created["id"]).current_status, "二面")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(service.get_task(second["task_id"])["result"]["already_processed"], 1)


if __name__ == "__main__":
    unittest.main()
