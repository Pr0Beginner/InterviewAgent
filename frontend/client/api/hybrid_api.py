from __future__ import annotations

import os
import json
import mimetypes
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

from client.api.base import ApiClient


class ApiRequestError(RuntimeError):
    """服务端请求无法完成时抛出的用户可读异常。"""


class HybridApiClient(ApiClient):
    """全部业务功能的 HTTP 客户端，正式运行时不会回退到 Mock 数据。"""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """初始化真实 HTTP 接口客户端。
        
        参数:
            base_url: 服务端接口根地址；默认使用 INTERVIEW_ASSISTANT_API_URL
                环境变量，未设置时使用本地 FastAPI 地址。
            timeout_seconds: 单次 HTTP 请求的超时时间，单位为秒。
            transport: 可选的 HTTPX 传输层实现，用于自动化测试。
        """
        super().__init__()
        resolved_url = base_url or os.getenv(
            "INTERVIEW_ASSISTANT_API_URL", "http://127.0.0.1:8000/api"
        )
        self._http = httpx.Client(
            base_url=resolved_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            trust_env=False,
        )
        self._chat_url = str(httpx.URL(resolved_url).copy_with(
            path="/v1/chat/completions", query=None, fragment=None,
        ))
        self._transport = transport

    @staticmethod
    def _business_request(name: str, params: dict) -> tuple[str, str, dict]:
        """将具名的界面操作映射为接口文档约定的 HTTP 方法、路径和请求体。"""
        params = dict(params)
        paths = {
            "sync_email": ("POST", "/email/sync"),
            "create_email_candidates": ("POST", "/email/candidates/create"),
            "recommend_jobs": ("POST", "/job-recommendations"),
            "create_mock_interview": ("POST", "/mock-interviews"),
        }
        if name in paths:
            method, path = paths[name]
        elif name == "get_job_recommendation":
            method, path = "GET", f"/job-recommendations/{params.pop('recommendation_id')}"
        elif name == "get_task":
            method, path = "GET", f"/tasks/{params.pop('task_id')}"
        elif name == "get_mock_interview":
            method, path = "GET", f"/mock-interviews/{params.pop('session_id')}"
        elif name in {"submit_mock_answer", "finish_mock_interview"}:
            session_id = params.pop("session_id")
            method, path = "POST", f"/mock-interviews/{session_id}/" + ("answers" if name == "submit_mock_answer" else "finish")
        else:
            raise ValueError("Unsupported business operation")
        body = {key: value for key, value in params.items() if value is not None}
        return method, path, body

    def _business_call(self, name: str, params: dict) -> dict:
        """同步执行具名业务请求，供命令行或非界面调用方使用。"""
        method, path, body = self._business_request(name, params)
        return self._request(method, path, timeout=180.0, **({"json": body} if method != "GET" else {}))

    async def invoke_async(self, name: str, **params) -> dict:
        """在界面工作线程的事件循环中执行可取消的耗时业务请求。"""
        if name == "upload_resume":
            return await self._upload_resume_async(params["file_path"])
        method, path, body = self._business_request(name, params)
        try:
            async with httpx.AsyncClient(base_url=str(self._http.base_url), timeout=180.0,
                                         trust_env=False, transport=self._transport) as client:
                response = await client.request(method, path, **({"json": body} if method != "GET" else {}))
                if response.is_error:
                    raise ApiRequestError(_response_error(response))
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ApiRequestError("服务端响应格式错误。")
                return payload
        except httpx.RequestError as exc:
            raise ApiRequestError("请求失败或超时，请检查服务端连接。") from exc

    def sync_email(self, limit=50, scope="unread", extensions=None):
        """提交邮件扫描请求，范围支持未读、已读和全部。"""
        return self._business_call("sync_email", {
            "limit": limit, "scope": scope, "extensions": extensions,
        })

    def create_email_candidates(self, candidate_ids):
        """创建邮件审核表中由用户明确选中的投递记录。"""
        return self._business_call(
            "create_email_candidates", {"candidate_ids": candidate_ids}
        )

    def recommend_jobs(self, cities, work_experience="应届生", tech_stack=None, business_preferences=None, keywords=None, page=1, page_size=10, extensions=None):
        """按指定求职条件和筛选参数获取一页岗位推荐。"""
        return self._business_call("recommend_jobs", {"cities": cities, "work_experience": work_experience,
            "tech_stack": tech_stack or [],
            "business_preferences": business_preferences, "keywords": keywords,
            "page": page, "page_size": page_size, "extensions": extensions})

    def get_job_recommendation(self, recommendation_id):
        """根据推荐记录 ID 获取已保存的岗位详情。"""
        return self._business_call("get_job_recommendation", {"recommendation_id": recommendation_id})

    def upload_resume(self, file_path):
        """以 multipart/form-data 上传本地简历文件。"""
        path = Path(file_path)
        with path.open("rb") as stream:
            return self._request("POST", "/mock-interviews/resumes", timeout=60.0, files={
                "file": (path.name, stream, mimetypes.guess_type(path.name)[0] or "application/octet-stream"),
            })

    async def _upload_resume_async(self, file_path):
        """在页面工作线程中异步上传简历，避免阻塞 Qt 界面。"""
        path = Path(file_path)
        try:
            async with httpx.AsyncClient(
                base_url=str(self._http.base_url), timeout=60.0,
                trust_env=False, transport=self._transport,
            ) as client:
                with path.open("rb") as stream:
                    response = await client.post("/mock-interviews/resumes", files={
                        "file": (path.name, stream, mimetypes.guess_type(path.name)[0] or "application/octet-stream"),
                    })
                if response.is_error:
                    raise ApiRequestError(_response_error(response))
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ApiRequestError("服务端响应格式错误。")
                return payload
        except OSError as exc:
            raise ApiRequestError("无法读取所选简历文件。") from exc
        except httpx.RequestError as exc:
            raise ApiRequestError("简历上传失败，请检查服务端连接。") from exc

    def create_mock_interview(self, company_name, position_name, interview_round, interview_focus=None, resume_id=None, extensions=None):
        """根据目标公司、岗位和考察方向创建由模型驱动的模拟面试。"""
        return self._business_call("create_mock_interview", {"company_name": company_name, "position_name": position_name,
            "interview_round": interview_round, "interview_focus": interview_focus,
            "resume_id": resume_id, "extensions": extensions})

    def submit_mock_answer(self, session_id, question_id, answer, extensions=None):
        """为指定的待回答题目提交答案。"""
        return self._business_call("submit_mock_answer", {"session_id": session_id, "question_id": question_id, "answer": answer, "extensions": extensions})

    def finish_mock_interview(self, session_id, extensions=None):
        """结束指定面试，并获取已保存的总结。"""
        return self._business_call("finish_mock_interview", {"session_id": session_id, "extensions": extensions})

    def get_task(self, task_id):
        """读取已接收的邮件扫描任务的状态和统计数量。"""
        return self._business_call("get_task", {"task_id": task_id})

    def get_mock_interview(self, session_id):
        """根据会话 ID 恢复已保存的模拟面试。"""
        return self._business_call("get_mock_interview", {"session_id": session_id})

    def create_chat_completion(
        self, messages: list[dict[str, str]], model: str = "interview-assistant",
        metadata: dict[str, str] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """使用对话消息、Agent 模型名、元数据和扩展参数请求 JSON 响应。"""
        return self._request("POST", self._chat_url, timeout=150.0, json={
            "model": model, "messages": messages, "stream": False,
            "metadata": metadata or {}, "extensions": extensions or {},
        })

    async def stream_chat_completion(
        self, messages: list[dict[str, str]], model: str = "interview-assistant",
        metadata: dict[str, str] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """读取 SSE 响应块；取消请求时关闭连接及连接池。
        
        参数:
            messages: 按时间排序的对话，包含本次用户消息。
            model: Agent 对外模型别名。
            metadata: 当前页面和会话 ID，不包含模型供应商凭证。
            extensions: 可选的项目扩展 Map。
        
        异常:
            ApiRequestError: HTTP 错误、SSE 错误事件或响应流被截断时抛出。
        """
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(150.0, connect=10.0), trust_env=False,
                transport=self._transport,
            ) as client:
                async with client.stream("POST", self._chat_url, json={
                    "model": model, "messages": messages, "stream": True,
                    "stream_options": {"include_usage": True},
                    "metadata": metadata or {}, "extensions": extensions or {},
                }) as response:
                    if response.is_error:
                        await response.aread()
                        raise ApiRequestError(_response_error(response))
                    if "text/event-stream" not in response.headers.get("content-type", ""):
                        raise ApiRequestError("服务端未返回 SSE 消息流。")
                    finished = False
                    data_lines: list[str] = []
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data_lines.append(line[5:].lstrip(" "))
                        elif not line and data_lines:
                            data = "\n".join(data_lines)
                            data_lines.clear()
                            if data == "[DONE]":
                                if not finished:
                                    raise ApiRequestError("Agent 回复未完整结束，请重试。")
                                return
                            try:
                                event = json.loads(data)
                            except ValueError as exc:
                                raise ApiRequestError("Agent 返回了无法解析的消息。") from exc
                            if not isinstance(event, dict):
                                raise ApiRequestError("Agent 消息格式错误。")
                            if "error" in event:
                                raise ApiRequestError(event["error"].get("message", "Agent 处理失败。"))
                            if event.get("object") != "chat.completion.chunk":
                                raise ApiRequestError("Agent 消息格式错误。")
                            for choice in event.get("choices", []):
                                finished = finished or choice.get("finish_reason") is not None
                            yield event
                    raise ApiRequestError("Agent 连接中断，回复可能不完整。")
        except httpx.TimeoutException as exc:
            raise ApiRequestError("Agent 响应超时，请稍后重试。") from exc
        except httpx.RequestError as exc:
            raise ApiRequestError("无法连接 Agent 服务，请确认后端已经启动。") from exc

    def close(self) -> None:
        """界面退出时关闭可复用的 HTTP 连接池。"""
        self._http.close()

    def list_interviews(
        self,
        company_name: str | None = None,
        position_name: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """从 FastAPI 服务加载一页投递记录。
        
        参数:
            company_name: 可选的公司名称包含匹配条件。
            position_name: 可选的岗位名称包含匹配条件。
            status: 可选的精确状态条件；“全部”表示不按状态筛选。
            page: 页码，从 1 开始。
            page_size: 每页最多返回的记录数。
        
        返回值:
            可直接用于投递状态页的服务端分页响应。
        """
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if company_name:
            params["company_name"] = company_name
        if position_name:
            params["position_name"] = position_name
        if status and status != "全部":
            params["status"] = status
        return self._request("GET", "/interviews", params=params)

    def update_interview_status(
        self,
        interview_id: int,
        target_status: str,
        interview_time: str | None = None,
        note: str | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """通过真实服务端更新一条投递记录的状态。
        
        参数:
            interview_id: 投递记录 ID。
            target_status: 新的投递状态。
            interview_time: 可选的新面试时间。
            note: 可选的状态历史备注。
            extensions: 用于后续兼容的可选请求扩展参数。
        
        返回值:
            更新后的状态及同步信息。
        """
        payload: dict[str, Any] = {"target_status": target_status}
        if interview_time is not None:
            payload["interview_time"] = _to_iso_datetime(interview_time)
        if note is not None:
            payload["note"] = note
        if extensions is not None:
            payload["extensions"] = extensions
        return self._request(
            "PATCH",
            f"/interviews/{interview_id}/status",
            json=payload,
        )

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
        """持久化投递状态页中一行的全部可编辑字段。
        
        参数:
            interview_id: 投递记录 ID。
            company_name: 修改后的公司名称。
            position_name: 修改后的岗位名称。
            base_location: 修改后的工作地点。
            current_status: 选中的投递状态。
            interview_time: 选中的开始时间，无时间时为 None。
            interview_end_time: 选中的结束时间，无时间时为 None。
            extensions: 用于后续兼容的可选请求扩展参数。
        
        返回值:
            服务端已保存的投递记录。
        """
        payload: dict[str, Any] = {
            "company_name": company_name,
            "position_name": position_name,
            "base_location": base_location,
            "current_status": current_status,
            "interview_time": _to_iso_datetime(interview_time),
            "interview_end_time": _to_iso_datetime(interview_end_time),
        }
        if extensions is not None:
            payload["extensions"] = extensions
        return self._request("PATCH", f"/interviews/{interview_id}", json=payload)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """发送一次服务端请求，并统一处理网络及接口错误。
        
        参数:
            method: HTTP 方法名。
            path: 相对于已配置接口根地址的路径。
            **kwargs: 传递给 httpx.Client.request 的请求参数。
        
        返回值:
            服务端返回并解码后的 JSON 对象。
        
        异常:
            ApiRequestError: 无法连接服务端或服务端返回错误时抛出。
        """
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise ApiRequestError(
                "无法连接服务端，请确认后端已经启动。"
            ) from exc

        if response.is_error:
            raise ApiRequestError(_response_error(response))

        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiRequestError("服务端返回了无法解析的数据。") from exc
        if not isinstance(payload, dict):
            raise ApiRequestError("服务端响应格式不正确。")
        return payload


def _response_error(response: httpx.Response) -> str:
    """从 HTTP 响应提取用户可读的错误说明，无法提取时使用状态码提示。"""
    fallback = f"服务端请求失败（HTTP {response.status_code}）"
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        return error.get("message", fallback) if isinstance(error, dict) else fallback
    except ValueError:
        return fallback


def _to_iso_datetime(value: str | None) -> str | None:
    """将界面日期格式转换为兼容 ISO 8601 的字符串。
    
    参数:
        value: 界面时间戳，例如 2026-10-08 14:00；也可以为 None。
    
    返回值:
        日期与时间之间使用 T 分隔的时间戳，或 None。
    """
    return value.replace(" ", "T", 1) if value else None
