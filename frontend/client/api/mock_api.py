from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from collections.abc import AsyncIterator
from time import time
from typing import Any
from uuid import uuid4

from client.api.base import ApiClient
from client.mock_data import INTERVIEWS, JOB_RECOMMENDATIONS, MOCK_INTERVIEW_QUESTIONS


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class MockApiClient(ApiClient):
    """所有前端接口的内存模拟实现。"""

    INTERVIEW_STATUSES = {
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
    }

    def __init__(self) -> None:
        self._interviews = deepcopy(INTERVIEWS)
        self._jobs = deepcopy(JOB_RECOMMENDATIONS)
        self._mock_sessions: dict[str, dict[str, Any]] = {}

    def create_chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str = "interview-assistant",
        metadata: dict[str, str] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """为隔离的前端测试返回固定结果。
        
        参数:
            messages: 按时间排序的 role/content 消息列表。
            model: Agent 对外模型别名。
            metadata: 字符串 Map，通过 page_context 选择测试回复。
            extensions: 预留的请求扩展 Map。
        """
        page_context = (metadata or {}).get("page_context", "applications")
        reply = self._build_agent_reply(messages[-1]["content"], page_context)
        return {
            "id": f"chatcmpl-{uuid4().hex}", "object": "chat.completion",
            "created": int(time()), "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": reply},
                         "finish_reason": "stop"}],
        }

    async def stream_chat_completion(
        self, messages: list[dict[str, str]], model: str = "interview-assistant",
        metadata: dict[str, str] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """使用相同的 messages、model、metadata 参数逐个生成模拟响应块。"""
        response = self.create_chat_completion(messages, model, metadata, extensions)
        identity = {key: response[key] for key in ("id", "model", "created")}
        identity["object"] = "chat.completion.chunk"
        yield {**identity, "choices": [{"index": 0, "delta": response["choices"][0]["message"], "finish_reason": None}]}
        yield {**identity, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}

    def list_interviews(
        self,
        company_name: str | None = None,
        position_name: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, page_size)
        records = sorted(
            self._interviews,
            key=lambda record: (
                record.get("interview_time") is not None,
                record.get("interview_time") or "",
                record["id"],
            ),
            reverse=True,
        )
        if company_name:
            records = [r for r in records if company_name.lower() in r["company_name"].lower()]
        if position_name:
            records = [r for r in records if position_name.lower() in r["position_name"].lower()]
        summary_records = records
        status_counts = {
            current_status: sum(
                record["current_status"] == current_status for record in summary_records
            )
            for current_status in (
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
            )
        }
        if status and status != "全部":
            records = [r for r in records if r["current_status"] == status]
        start = max(page - 1, 0) * page_size
        total = len(records)
        total_pages = max(1, (total + page_size - 1) // page_size)
        return {
            "items": deepcopy(records[start : start + page_size]),
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "summary": {
                "total": len(summary_records),
                "status_counts": status_counts,
            },
        }

    def update_interview_status(
        self,
        interview_id: int,
        target_status: str,
        interview_time: str | None = None,
        note: str | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = next((r for r in self._interviews if r["id"] == interview_id), None)
        if record is None:
            raise KeyError(f"Interview record {interview_id} not found")
        if target_status not in self.INTERVIEW_STATUSES:
            raise ValueError(f"Unsupported interview status: {target_status}")
        previous_status = record["current_status"]
        record["current_status"] = target_status
        if interview_time is not None:
            record["interview_time"] = interview_time
        record["updated_at"] = _now()
        return {
            "id": interview_id,
            "previous_status": previous_status,
            "current_status": target_status,
            "interview_time": record["interview_time"],
            "note": note,
            "updated_at": record["updated_at"],
        }

    def update_interview(
        self,
        interview_id: int,
        company_name: str,
        position_name: str,
        base_location: str,
        current_status: str,
        interview_time: str | None,
        interview_end_time: str | None,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = next((r for r in self._interviews if r["id"] == interview_id), None)
        if record is None:
            raise KeyError(f"Interview record {interview_id} not found")
        if current_status not in self.INTERVIEW_STATUSES:
            raise ValueError(f"Unsupported interview status: {current_status}")
        record.update(
            {
                "company_name": company_name,
                "position_name": position_name,
                "base_location": base_location,
                "current_status": current_status,
                "interview_time": interview_time,
                "interview_end_time": interview_end_time,
                "updated_at": _now(),
            }
        )
        return deepcopy(record)

    def sync_email(
        self, limit: int = 50, scope: str = "unread",
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id = f"mail-{uuid4().hex[:8]}"
        return {"task_id": task_id, "status": "accepted", "created_at": _now(),
                "limit": limit, "scope": scope}

    def recommend_jobs(
        self,
        cities: list[str],
        tech_stack: list[str],
        business_preferences: list[str] | None = None,
        keywords: list[str] | None = None,
        page: int = 1,
        page_size: int = 10,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, page_size)
        jobs = self._jobs
        if cities:
            jobs = [job for job in jobs if job["base_location"] in cities]
        if keywords:
            normalized = [keyword.lower() for keyword in keywords]
            jobs = [
                job
                for job in jobs
                if any(
                    keyword in f"{job['company_name']} {job['position_name']} {job['job_description']}".lower()
                    for keyword in normalized
                )
            ]
        total = len(jobs)
        total_pages = max(1, (total + page_size - 1) // page_size)
        start = (page - 1) * page_size
        return {
            "items": deepcopy(jobs[start : start + page_size]),
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
        }

    def get_job_recommendation(self, recommendation_id: str) -> dict[str, Any]:
        job = next((job for job in self._jobs if job["id"] == recommendation_id), None)
        if job is None:
            raise KeyError(f"Job recommendation {recommendation_id} not found")
        return deepcopy(job)

    def create_mock_interview(
        self,
        company_name: str | None,
        position_name: str,
        interview_round: str,
        interview_focus: list[str] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = f"mock-{uuid4().hex[:8]}"
        self._mock_sessions[session_id] = {
            "company_name": company_name,
            "position_name": position_name,
            "interview_round": interview_round,
            "interview_focus": interview_focus or [],
            "question_index": 0,
            "answers": [],
        }
        return {
            "session_id": session_id,
            "question_id": "q-1",
            "question": MOCK_INTERVIEW_QUESTIONS[0],
            "status": "in_progress",
            "created_at": _now(),
        }

    def submit_mock_answer(
        self,
        session_id: str,
        question_id: str,
        answer: str,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self._mock_sessions.get(session_id)
        if session is None:
            raise KeyError(f"Mock interview {session_id} not found")
        session["answers"].append({"question_id": question_id, "answer": answer})
        score = min(95, max(55, 55 + len(answer.strip()) // 4))
        session["question_index"] += 1
        index = session["question_index"]
        completed = index >= len(MOCK_INTERVIEW_QUESTIONS)
        return {
            "evaluation": "回答结构清晰；可以进一步补充量化结果和关键取舍。",
            "score": score,
            "question_id": None if completed else f"q-{index + 1}",
            "question": None if completed else MOCK_INTERVIEW_QUESTIONS[index],
            "is_follow_up": False,
            "status": "completed" if completed else "in_progress",
        }

    def finish_mock_interview(
        self, session_id: str, extensions: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        session = self._mock_sessions.get(session_id)
        if session is None:
            raise KeyError(f"Mock interview {session_id} not found")
        answer_count = len(session["answers"])
        return {
            "session_id": session_id,
            "overall_score": 78 if answer_count else 0,
            "summary": f"本次共完成 {answer_count} 道题，基础知识较扎实，项目表达仍可加强。",
            "strengths": ["Java 基础较扎实", "能够说明核心实现思路"],
            "weaknesses": ["缺少部分量化指标", "系统设计取舍说明不足"],
            "suggestions": ["使用 STAR 结构组织项目回答", "补充性能优化前后的数据对比"],
            "finished_at": _now(),
        }

    def _build_agent_reply(self, message: str, page_context: str) -> str:
        if page_context == "recommendations":
            return f"当前有 {len(self._jobs)} 个高匹配岗位，我可以结合 JD、Base 地和技术栈帮你判断投递优先级。"
        if page_context == "mock_interview":
            return "当前处于模拟面试页。选择目标公司、岗位和轮次后，我会一次提出一个问题并根据回答追问。"
        if "推荐" in message or "岗位" in message:
            return f"当前有 {len(self._jobs)} 个高匹配岗位，可以在“推荐岗位”页面查看 JD 和投递链接。"
        if "模拟" in message or "面试训练" in message:
            return "可以开始模拟面试。请在“模拟面试”页面选择岗位和面试轮次。"
        if "面试" in message or "投递" in message:
            active = [
                record
                for record in self._interviews
                if record["current_status"] in {"笔试中", "待面试", "一面", "二面", "三面", "HR面"}
            ]
            return f"当前共有 {len(active)} 个进行中的笔试或面试流程。"
        return "我可以查询或更新面试状态、推荐岗位，也可以进行模拟面试。"
