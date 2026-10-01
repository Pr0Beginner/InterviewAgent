"""使用 SQLite 保存检查点、使用 MySQL 保存执行凭据的 LangGraph 业务图。"""

from datetime import datetime
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import select

from backend.app.core.exceptions import ApplicationError
from backend.app.db.mysql import get_session_factory
from backend.app.db.state import get_langgraph_sqlite_path
from backend.app.integrations.feishu import FeishuClient
from backend.app.models import AgentOperation, JobApplication, ApplicationStatusHistory
from backend.app.schemas.business import ChangeInterview, CreateInterview
from backend.app.schemas.interviews import InterviewRecord
from backend.app.services.sync import queue_sync, sync_feishu


class BusinessState(TypedDict, total=False):
    """检查点仅包含已校验的业务数据，不包含邮件正文或密钥。"""
    operation_id: str
    arguments: dict
    result: dict
    mysql: dict
    feishu: dict
    create: bool


class InterviewWorkflows:
    """查询和修改业务图；存储与连接器可注入，便于测试。"""

    def __init__(self, session_factory=None, checkpoint_path=None, feishu=None):
        """配置 SQLAlchemy 会话工厂、SQLite 检查点文件和飞书适配器。"""
        self.factory = session_factory or get_session_factory()
        self.checkpoint_path = str(checkpoint_path or get_langgraph_sqlite_path())
        self.feishu = feishu or FeishuClient()

    def _invoke(self, builder, state: BusinessState) -> dict:
        """执行一次业务图，并持久化各节点的状态变更。"""
        with SqliteSaver.from_conn_string(self.checkpoint_path) as saver:
            graph = builder.compile(checkpointer=saver)
            result = graph.invoke(state, {"configurable": {"thread_id": state["operation_id"]}})
            return result["result"]

    def query(self, arguments: dict) -> dict:
        """分别查询 MySQL 和飞书，汇总差异但不覆盖原数据。"""
        def mysql(state):
            """使用已校验的业务图参数查询指定数据库分页。"""
            from backend.app.agent.tools import InterviewQuery, run_interview_query
            return {"mysql": run_interview_query(InterviewQuery.model_validate(state["arguments"]), self.factory)}

        def feishu(state):
            """读取远端记录；连接器失败时返回错误信息，同时保留本地查询结果。"""
            try:
                return {"feishu": self.feishu.read()}
            except ApplicationError as exc:
                return {"feishu": {"status": "failed", "error": exc.message, "records": []}}

        def merge(state):
            """返回查询记录及对应的远端状态冲突。"""
            data = dict(state["mysql"])
            if state["feishu"].get("source_type") == "progress_sheet":
                from backend.app.integrations.feishu_sources import business_key
                remote_rows = state["feishu"]["records"]
                arguments = state["arguments"]
                matches = [row for row in remote_rows
                           if (not arguments.get("company_name") or arguments["company_name"] in row["company_name"])
                           and (not arguments.get("position_name") or arguments["position_name"] in row["position_name"])
                           and (not arguments.get("status") or arguments["status"] == row["current_status"])]
                page, size = arguments.get("page", 1), arguments.get("page_size", 20)
                conflicts = []
                for row in data["items"]:
                    other = [item for item in remote_rows if business_key(item) == business_key(row)]
                    if len(other) == 1 and other[0]["current_status"] and other[0]["current_status"] != row["current_status"]:
                        conflicts.append({"id": row["id"], "mysql_status": row["current_status"], "feishu_status": other[0]["current_status"]})
                data.update(feishu_sync_status="success", conflicts=conflicts, feishu_total=len(matches),
                            feishu_records=matches[(page - 1) * size:page * size], feishu_has_next=page * size < len(matches),
                            schedule_status=state["feishu"]["schedule"]["status"], needs_review=state["feishu"].get("needs_review", []))
                return {"result": data}
            remote = {row["id"]: row for row in state["feishu"]["records"]}
            conflicts = []
            for row in data["items"]:
                other = remote.get(row["id"])
                if other and other["current_status"] != row["current_status"]:
                    conflicts.append({"id": row["id"], "mysql_status": row["current_status"], "feishu_status": other["current_status"]})
            data.update(feishu_sync_status=state["feishu"]["status"], conflicts=conflicts)
            if "error" in state["feishu"]:
                data["feishu_error"] = state["feishu"]["error"]
            return {"result": data}

        graph = StateGraph(BusinessState)
        graph.add_node("query_mysql", mysql)
        graph.add_node("read_feishu", feishu)
        graph.add_node("merge_status", merge)
        graph.add_edge(START, "query_mysql")
        graph.add_edge(START, "read_feishu")
        graph.add_edge(["query_mysql", "read_feishu"], "merge_status")
        graph.add_edge("merge_status", END)
        return self._invoke(graph, {"operation_id": "query-" + uuid4().hex, "arguments": arguments})

    def mutate(self, arguments: dict, operation_id: str, create=False) -> dict:
        """依次校验、提交 MySQL、同步飞书并返回结果，保留同步失败记录。"""
        graph = StateGraph(BusinessState)
        graph.add_node("validate_change", self._validate)
        graph.add_node("write_mysql", self._write)
        graph.add_node("sync_feishu", self._sync)
        graph.add_edge(START, "validate_change")
        graph.add_edge("validate_change", "write_mysql")
        graph.add_edge("write_mysql", "sync_feishu")
        graph.add_edge("sync_feishu", END)
        return self._invoke(graph, {"operation_id": operation_id, "arguments": arguments, "create": create})

    def _validate(self, state):
        """事务开始前校验参数结构；重复执行时复用已有执行凭据。"""
        model = CreateInterview if state["create"] else ChangeInterview
        model.model_validate(state["arguments"])
        return {}

    def _write(self, state):
        """在同一事务中提交业务变更、审计记录、待同步项和幂等凭据。"""
        with self.factory() as session:
            receipt = session.get(AgentOperation, state["operation_id"])
            if receipt:
                return {"result": receipt.result}
            args = state["arguments"]
            if state["create"]:
                request = CreateInterview.model_validate(args)
                matches = list(session.scalars(select(JobApplication).where(
                    JobApplication.company_name == request.company_name,
                    JobApplication.position_name == request.position_name,
                    JobApplication.base_location == request.base_location)))
                if matches:
                    raise ApplicationError("APPLICATION_EXISTS", "该公司、岗位与 Base 已有记录，请先查询。", status_code=409)
                row = JobApplication(company_name=request.company_name, position_name=request.position_name,
                    base_location=request.base_location, current_status=request.current_status.value,
                    interview_time=request.interview_time, job_url=str(request.job_url) if request.job_url else None)
                session.add(row)
                session.flush()
                previous_status = None
                note = "通过 Agent 创建"
            else:
                request = ChangeInterview.model_validate(args)
                row = session.scalar(select(JobApplication).where(JobApplication.id == request.interview_id).with_for_update())
                if row is None:
                    raise ApplicationError("INTERVIEW_NOT_FOUND", "投递记录不存在。", status_code=404)
                if row.current_status != request.expected_status.value:
                    raise ApplicationError("STATUS_CONFLICT", "记录已被修改，请重新查询后操作。", status_code=409)
                previous_status = row.current_status
                if "company_name" in request.model_fields_set:
                    row.company_name = request.company_name
                if "position_name" in request.model_fields_set:
                    row.position_name = request.position_name
                if "base_location" in request.model_fields_set:
                    row.base_location = request.base_location
                if "target_status" in request.model_fields_set:
                    row.current_status = request.target_status.value
                if "interview_time" in request.model_fields_set:
                    row.interview_time = request.interview_time
                if "job_url" in request.model_fields_set:
                    row.job_url = str(request.job_url) if request.job_url else None
                note = request.note
            row.updated_at = datetime.now()
            if previous_status != row.current_status:
                session.add(ApplicationStatusHistory(application_id=row.id, previous_status=previous_status,
                    current_status=row.current_status, change_source="agent", note=note))
            queue_sync(session, row.id)
            result = InterviewRecord.model_validate(row).model_dump(mode="json")
            result.update(previous_status=previous_status, feishu_sync_status="pending")
            session.add(AgentOperation(id=state["operation_id"], result=result))
            session.commit()
            return {"result": result}

    def _sync(self, state):
        """尝试远端同步；同步失败不改变已提交数据库写入的成功状态。"""
        result = dict(state["result"])
        try:
            sync_feishu(self.factory, self.feishu)
            result["feishu_sync_status"] = "success"
        except ApplicationError as exc:
            result["feishu_sync_status"] = "pending"
            result["sync_message"] = exc.message
        return {"result": result}
