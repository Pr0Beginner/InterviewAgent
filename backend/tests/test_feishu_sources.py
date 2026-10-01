"""三来源接入、个人面经边界、原表同步和邮箱只读行为的回归测试。"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import select, func

from backend.app.core.config import Settings
from backend.app.core.exceptions import ApplicationError
from backend.app.integrations.feishu import FeishuClient
from backend.app.integrations.feishu_sources import FeishuSources, local_time, business_key
from backend.app.integrations.mail import NeteaseMailbox
from backend.app.models import JobApplication, ApplicationStatusHistory, FeishuSyncItem
from backend.app.schemas.business import MockInterviewRequest
from backend.app.services.mock_interviews import MockInterviewService
from backend.app.services.sync import sync_feishu, queue_sync
from backend.tests.test_business import StoreTest, FakeModel


class FeishuSourceTest(unittest.TestCase):
    def setUp(self):
        """每个测试显式禁用真实环境文件及外部请求。"""
        self.settings = Settings(_env_file=None, feishu_progress_token="progress", feishu_interview_question_token="index", feishu_interview_date_token="dates")
        self.client = FeishuClient(self.settings)
        self.sources = FeishuSources(self.client)

    def test_new_config_names_and_beijing_timezone(self):
        """用户配置名称可加载；UTC 时间转换为北京时间。"""
        with patch.dict("os.environ", {"FEISHU_InterviewDate_TOKEN": "date-url", "FEISHU_Progress_TOKEN": "progress-url", "FEISHU_InterviewQuestion_TOKEN": "question-url"}):
            settings = Settings(_env_file=None)
        self.assertEqual(settings.feishu_interview_date_token, "date-url")
        self.assertEqual(settings.feishu_progress_token, "progress-url")
        self.assertEqual(settings.feishu_interview_question_token, "question-url")
        self.assertEqual(local_time("2026-10-08T09:30:00Z"), "2026-10-08T17:30:00")
        self.assertIsNone(local_time(None))

    def test_progress_preserves_real_row_coordinates_and_multiline_cells(self):
        """原序号不是数据库 ID，字段内换行也不会改变实际行定位。"""
        payload = {"annotated_csv": '[row=1] 序号,单位,部门,地点,状态,结果\n[row=8] 999,BIGO,"后端\n研发",深圳,待面试,流程中',
                   "col_indices": list("ABCDEF"), "row_indices": [1, 8], "revision": 5, "has_more": False}
        with patch.object(self.sources, "_sheet_target", return_value={"token": "book", "sheet_id": "sheet", "sheet_info": {"row_count": 8}}), patch.object(self.client, "_run", return_value=payload):
            result = self.sources._progress()
        row = result["records"][0]
        self.assertEqual(row["source_row"], 8)
        self.assertEqual(row["id"], "book:sheet:8")
        self.assertEqual(row["position_name"], "后端\n研发")
        self.assertEqual(row["attendance_status"], "待面试")
        self.assertEqual(row["current_status"], "待面试")

    def test_invitation_keeps_pending_status_with_an_explicit_future_date(self):
        """未来安排只补充时间；尚未参加时仍保持待面试状态。"""
        progress = {"records": [{"id": "r", "company_name": "BIGO", "position_name": "", "current_status": "待面试", "raw_status": "待面试"}]}
        schedule = {"status": "success", "events": [{"record_id": "date", "title": "BIGO 一面", "position_name": "", "start_time": "2099-10-08T17:30:00", "end_time": "2099-10-08T18:30:00"}]}
        with patch.object(self.sources, "_progress", return_value=progress), patch.object(self.sources, "read_schedule", return_value=schedule):
            result = self.sources.read()
        self.assertEqual(result["records"][0]["current_status"], "待面试")
        self.assertEqual(result["records"][0]["raw_status"], "待面试")
        self.assertEqual(result["records"][0]["interview_time"], "2099-10-08T17:30:00")
        self.assertEqual(result["records"][0]["interview_end_time"], "2099-10-08T18:30:00")

    def test_experience_follows_index_and_stops_before_another_owner(self):
        """只请求 ZMY 章节，即使返回范围出现其他标题也停止处理。"""
        replies = [
            {"document": {"content": '<fragment><outline><h4 id="index">面经</h4></outline></fragment>'}},
            {"document": {"content": '<fragment><h4 id="index">面经</h4><p><cite type="doc" doc-id="experience"/></p></fragment>'}},
            {"document": {"content": '<fragment><outline><h2 id="owner">ZMY</h2><h2 id="other">SF</h2></outline></fragment>'}},
            {"document": {"document_id": "experience", "revision_id": 4, "content": '<fragment><h2 id="owner">ZMY</h2><h3>小米</h3><ol><li>自己的题目</li></ol><h2 id="other">SF</h2><h3>其他公司</h3><p>绝不能进入模型的内容</p></fragment>'}},
        ]
        with patch.object(self.client, "_run", side_effect=replies) as run:
            result = self.sources.read_experience()
        self.assertEqual(result["owner"], "ZMY")
        self.assertEqual([item["title"] for item in result["sections"]], ["小米"])
        self.assertNotIn("绝不能", json.dumps(result, ensure_ascii=False))
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--scope") + 1], "section")
        self.assertEqual(args[args.index("--start-block-id") + 1], "owner")

    def test_missing_or_duplicate_owner_does_not_read_the_full_document(self):
        """无法唯一定位个人标题时失败关闭，不退化到全篇读取。"""
        for xml in ('<h2 id="other">SF</h2>', '<h2 id="a">ZMY</h2><h2 id="b">ZMY</h2>'):
            with self.subTest(xml=xml), patch.object(self.client, "_run", return_value={"document": {"content": xml}}) as run:
                with self.assertRaises(ApplicationError):
                    self.sources.read_experience()
                self.assertEqual(run.call_count, 1)

    def test_schedule_consumes_all_ndjson_pages_and_respects_view(self):
        """所有分页在同一版本内读取，临时文件不留在项目目录。"""
        target = {"resource_type": "bitable", "base_token": "base", "table_id": "table", "view_id": "view"}
        def run(args, content=None, cwd=None):
            """用临时文件模拟 CLI 导出，只接受已经约定的参数。"""
            if args[:2] == ["base", "+url-resolve"]:
                return target
            if args[:2] == ["base", "+field-list"]:
                return {"fields": [{"name": name, "type": kind} for name, kind in {"事项": "text", "岗位/部门": "text", "开始时间": "datetime", "结束时间": "datetime"}.items()]}
            self.assertIn("view", args)
            offset = int(args[args.index("--offset") + 1])
            path = Path(cwd) / args[args.index("--output") + 1]
            path.write_text(json.dumps({"record_id": "date-" + str(offset), "事项": "BIGO 一面", "开始时间": "2026-10-08T17:30:00+08:00"}), encoding="utf-8")
            path.with_suffix(".manifest.json").write_text(json.dumps({"records_count": 1, "rev": 8, "has_more": offset == 0, "next_offset": 1}), encoding="utf-8")
            return {"manifest_version": "v1"}
        with patch.object(self.client, "_run", side_effect=run):
            result = self.sources.read_schedule()
        self.assertEqual(len(result["events"]), 2)

    def test_write_targets_original_cells_and_preserves_pending_invitation(self):
        """同轮次未来邀请仍显示待面试，不能因同步改成已参加。"""
        row = {"id": "source", "company_name": "BIGO", "position_name": "后端", "base_location": "深圳", "current_status": "一面",
               "raw_status": "待面试", "raw_result": "流程中", "source_row": 11, "interview_time": "2099-10-08T17:30:00"}
        current = {"target": {"token": "book", "sheet_id": "sheet"}, "records": [row], "columns": {"状态": "E", "结果": "F"}, "revision_id": 4}
        with patch.object(self.client, "_run", return_value={"revision": 4}) as run, patch.object(self.sources, "read", return_value=current):
            self.sources.write([{**row, "id": 1}], current)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][1], "+revision-get")
        with patch.object(self.client, "_run", return_value={"revision": 5}):
            with self.assertRaisesRegex(ApplicationError, "手动修改"):
                self.sources.write([{**row, "id": 1}], current)


class NativeFeishu:
    """原表同步的本机替身，不进行外部读写。"""
    def __init__(self):
        self.settings = SimpleNamespace(feishu_progress_token="test-native", feishu_document_token=None)
        self.records = [{"id": "source-1", "company_name": "测试公司", "position_name": "Java", "base_location": "杭州", "current_status": "一面", "interview_time": None},
                        {"id": "source-2", "company_name": "待确认公司", "position_name": "", "base_location": "", "current_status": "待面试", "raw_status": "待面试", "interview_time": None}]
        self.writes = 0

    def read(self):
        """返回独立快照，保留含糊记录供调用方展示。"""
        return {"status": "success", "source_type": "progress_sheet", "records": deepcopy(self.records),
                "schedule": {"status": "success", "events": []}, "needs_review": []}

    def write(self, rows, current):
        """仅更新本次推送行，其他记录保持不变。"""
        self.writes += 1
        for row in rows:
            other = next(item for item in self.records if business_key(item) == business_key(row))
            other.update(current_status=row["current_status"], interview_time=row["interview_time"],
                         interview_end_time=row.get("interview_end_time"))


class NativeSyncTest(StoreTest):
    def test_invalid_direction_rejected_before_external_read(self):
        """扩展 Map 中的方向仍须校验，错误类型不能触发外部访问。"""
        client = Mock()
        for direction in ("invalid", {}, [], None):
            with self.subTest(direction=direction), self.assertRaises(ApplicationError) as context:
                sync_feishu(self.factory, client, direction=direction)
            self.assertEqual(context.exception.status_code, 422)
        client.read.assert_not_called()

    def test_import_is_idempotent_and_pending_invitation_is_imported(self):
        """待面试作为明确状态正常导入，重复同步不会重复写入。"""
        client = NativeFeishu()
        first = sync_feishu(self.factory, client)
        second = sync_feishu(self.factory, client)
        self.assertEqual(first["imported_count"], 2)
        self.assertEqual(second["imported_count"], 0)
        self.assertEqual(len(first["needs_review"]), 0)
        self.assertEqual(client.writes, 0)
        with self.factory() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(JobApplication)), 2)
            self.assertEqual(session.scalar(select(func.count()).select_from(ApplicationStatusHistory)), 2)

    def test_push_only_pending_rows_and_reject_manual_remote_conflict(self):
        """同步只推送脏行，远端人工修改不会被本地状态覆盖。"""
        client = NativeFeishu()
        sync_feishu(self.factory, client)
        untouched = deepcopy(client.records[1])
        with self.factory() as session:
            row = session.scalar(select(JobApplication))
            row.current_status = "二面"
            queue_sync(session, row.id)
            session.commit()
        result = sync_feishu(self.factory, client)
        self.assertEqual(result["exported_count"], 1)
        self.assertEqual(client.records[1], untouched)
        with self.factory() as session:
            row = session.scalar(select(JobApplication))
            self.assertEqual(session.get(FeishuSyncItem, row.id).status, "success")
            row.current_status = "三面"
            queue_sync(session, row.id)
            session.commit()
        client.records[0]["current_status"] = "Offer"
        with self.assertRaisesRegex(ApplicationError, "手动修改"):
            sync_feishu(self.factory, client)
        self.assertEqual(client.writes, 1)

    def test_query_returns_remote_original_status_without_writes(self):
        """查询只返回远端事实，不给外部源 ID 冒充 MySQL ID。"""
        self.graphs.feishu = NativeFeishu()
        result = self.graphs.query({"company_name": "待确认"})
        self.assertEqual(result["items"], [])
        self.assertEqual(result["feishu_records"][0]["current_status"], "待面试")
        self.assertEqual(result["feishu_records"][0]["raw_status"], "待面试")
        self.assertEqual(result["feishu_total"], 1)
        self.assertEqual(self.graphs.feishu.writes, 0)

    def test_mock_receives_only_scoped_personal_experience(self):
        """模拟面试使用适配器返回的个人面经，不自行读取整篇文档。"""
        source = Mock()
        source.read_experience.return_value = {"status": "success", "sections": [{"title": "小米", "text": "Java 类加载机制"}], "source_url": "personal"}
        provider = FakeModel([{"question": "说明双亲委派。"}])
        service = MockInterviewService(self.factory, provider, feishu=source)
        created = asyncio.run(service.create(MockInterviewRequest(position_name="Java", interview_round="一面")))
        context = service.get(created["session_id"])["context"]
        self.assertEqual(context["personal_experience"]["owner"], "ZMY")
        self.assertEqual(context["personal_experience"]["sections"][0]["title"], "小米")


class MailUidValidityTest(unittest.TestCase):
    def test_scan_scope_maps_to_imap_search_criteria(self):
        """未读、已读和全部范围应映射到对应的 IMAP 查询条件。"""
        mailbox = NeteaseMailbox(Settings(_env_file=None, netease_email="example@163.com"))
        expected = {"unread": "UNSEEN", "read": "SEEN", "all": "ALL"}
        for scope, criteria in expected.items():
            with self.subTest(scope=scope):
                client = Mock(spec=["uid", "response", "status"])
                client.uid.return_value = ("OK", [b"5"])
                client.response.return_value = ("UIDVALIDITY", [b"1"])
                mailbox.messages(client, 1, scope)
                self.assertEqual(client.uid.call_args_list[0].args, ("search", None, criteria))

    def test_repeated_search_does_not_consume_uidvalidity_twice(self):
        """同一连接两次搜索复用 UIDVALIDITY，不会丢失去重依据。"""
        client = Mock(spec=["uid", "response", "status"])
        client.uid.return_value = ("OK", [b"5 6"])
        client.response.side_effect = [("UIDVALIDITY", [b"1"]), ("UIDVALIDITY", [None])]
        mailbox = NeteaseMailbox(Settings(_env_file=None, netease_email="example@163.com"))
        first = mailbox.unread(client, 2)
        self.assertEqual(first, mailbox.unread(client, 2))
        self.assertEqual(client.response.call_count, 1)
        client.status.assert_not_called()

    def test_status_fallback_and_connection_specific_identity(self):
        """服务器未发 UIDVALIDITY 时只读 STATUS 补取，新连接仍重新获取。"""
        mailbox = NeteaseMailbox(Settings(_env_file=None, netease_email="example@163.com"))
        identifiers = []
        for validity in (1, 2):
            client = Mock(spec=["uid", "response", "status"])
            client.uid.return_value = ("OK", [b"5"])
            client.response.return_value = ("UIDVALIDITY", [None])
            client.status.return_value = ("OK", [f'"INBOX" (UIDVALIDITY {validity})'.encode()])
            identifiers.append(mailbox.unread(client, 1)[0]["receipt_id"])
        self.assertNotEqual(*identifiers)


if __name__ == "__main__":
    unittest.main()
