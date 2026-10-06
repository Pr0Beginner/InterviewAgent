"""使用 LangGraph 编排本地投递记录的查询和修改。"""

from typing import TypedDict
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from backend.app.db.state import get_langgraph_sqlite_path
from backend.app.observability import observation, update_observation
from backend.app.schemas.business import ChangeInterview, CreateInterview
from backend.app.schemas.interviews import InterviewRecord
from backend.app.storage.local import LocalStateStore, MarkdownInterviewStore


class BusinessState(TypedDict, total=False):
    """图节点之间传递的已校验业务数据。"""

    operation_id: str
    arguments: dict
    result: dict
    create: bool


class InterviewWorkflows:
    """查询和修改本地 Markdown 投递记录的业务图。"""

    def __init__(
        self,
        store: MarkdownInterviewStore | None = None,
        checkpoint_path=None,
        state_store: LocalStateStore | None = None,
        settings=None,
    ) -> None:
        from backend.app.core.config import get_settings

        self.store = store or MarkdownInterviewStore()
        self.checkpoint_path = str(checkpoint_path or get_langgraph_sqlite_path())
        self.state_store = state_store or LocalStateStore()
        self.settings = settings or get_settings()

    def _observed_node(self, name, handler, as_type="span"):
        """为图节点添加受限观测，不改变 LangGraph 节点协议。"""
        def run(state):
            with observation(
                self.settings,
                name=name.replace("_", "-"),
                as_type=as_type,
                input=state,
            ) as current:
                try:
                    result = handler(state)
                except Exception as exc:
                    update_observation(current, level="ERROR", status_message=type(exc).__name__)
                    raise
                update_observation(current, output=result)
                return result
        return run

    def _invoke(self, builder, state: BusinessState, name: str) -> dict:
        """执行一次业务图，并把节点状态写入 SQLite 检查点。"""
        with observation(
            self.settings,
            name=name,
            as_type="chain",
            input=state,
            metadata={"operation_id": state["operation_id"]},
        ) as current:
            try:
                with SqliteSaver.from_conn_string(self.checkpoint_path) as saver:
                    graph = builder.compile(checkpointer=saver)
                    completed = graph.invoke(
                        state,
                        {"configurable": {"thread_id": state["operation_id"]}},
                    )
            except Exception as exc:
                update_observation(current, level="ERROR", status_message=type(exc).__name__)
                raise
            result = completed["result"]
            update_observation(current, output=result)
            return result

    def query(self, arguments: dict) -> dict:
        """从本地 Markdown 查询一页投递记录。"""

        def query_local(state: BusinessState) -> dict:
            from backend.app.agent.tools import InterviewQuery, run_interview_query

            request = InterviewQuery.model_validate(state["arguments"])
            return {"result": run_interview_query(request, self.store)}

        graph = StateGraph(BusinessState)
        graph.add_node(
            "query_local_records",
            self._observed_node("query_local_records", query_local, as_type="retriever"),
        )
        graph.add_edge(START, "query_local_records")
        graph.add_edge("query_local_records", END)
        return self._invoke(
            graph,
            {"operation_id": "query-" + uuid4().hex, "arguments": arguments},
            "query-interviews",
        )

    def mutate(self, arguments: dict, operation_id: str, create: bool = False) -> dict:
        """校验参数后原子写入本地 Markdown。"""
        graph = StateGraph(BusinessState)
        graph.add_node("validate_change", self._observed_node("validate_change", self._validate))
        graph.add_node("write_local_record", self._observed_node("write_local_record", self._write))
        graph.add_edge(START, "validate_change")
        graph.add_edge("validate_change", "write_local_record")
        graph.add_edge("write_local_record", END)
        return self._invoke(
            graph,
            {
                "operation_id": operation_id,
                "arguments": arguments,
                "create": create,
            },
            "mutate-interview",
        )

    @staticmethod
    def _validate(state: BusinessState) -> dict:
        """在写文件前完成请求结构和字段约束校验。"""
        model = CreateInterview if state["create"] else ChangeInterview
        model.model_validate(state["arguments"])
        return {}

    def _write(self, state: BusinessState) -> dict:
        """写入本地文件，并用操作凭据保证同一请求不会重复创建。"""
        operation_id = state["operation_id"]
        receipt = self.state_store.get("operations", operation_id)
        if receipt is not None:
            return {"result": receipt["result"]}

        if state["create"]:
            request = CreateInterview.model_validate(state["arguments"])
            row = self.store.create({
                "company_name": request.company_name,
                "position_name": request.position_name,
                "base_location": request.base_location,
                "current_status": request.current_status.value,
                "interview_time": request.interview_time,
                "interview_end_time": request.interview_end_time,
                "job_url": str(request.job_url) if request.job_url else None,
            })
            previous_status = None
        else:
            request = ChangeInterview.model_validate(state["arguments"])
            values = {}
            mapping = {
                "company_name": "company_name",
                "position_name": "position_name",
                "base_location": "base_location",
                "target_status": "current_status",
                "interview_time": "interview_time",
                "interview_end_time": "interview_end_time",
                "job_url": "job_url",
            }
            for request_field, stored_field in mapping.items():
                if request_field not in request.model_fields_set:
                    continue
                value = getattr(request, request_field)
                if request_field == "target_status":
                    value = value.value
                elif request_field == "job_url":
                    value = str(value) if value else None
                values[stored_field] = value
            row, previous_status = self.store.update(
                request.interview_id,
                values,
                expected_status=request.expected_status.value,
            )

        result = InterviewRecord.model_validate(row).model_dump(mode="json")
        result.update(previous_status=previous_status, storage="local_markdown")
        self.state_store.put("operations", operation_id, {"result": result})
        return {"result": result}
