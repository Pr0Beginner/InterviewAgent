"""限制调用轮次的 ReAct 工具循环，对外提供 OpenAI 兼容响应。"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from time import time
from typing import Any
from uuid import uuid4

from backend.app.agent.errors import AgentError
from backend.app.agent.context import ToolContextStore
from backend.app.agent.memory import (
    JobPreferenceMemoryStore,
    JobPreferenceSummary,
    PREFERENCE_MEMORY_INSTRUCTIONS,
)
from backend.app.agent.prompts import system_prompt
from backend.app.agent.provider import DeepSeekProvider
from backend.app.agent.tools import QUERY_TOOL, MUTATION_TOOLS, BUSINESS_TOOLS, execute_tool
from backend.app.core.config import Settings
from backend.app.observability import (
    observation,
    trace_attributes,
    update_observation,
)
from backend.app.schemas.chat import ChatCompletionRequest


LOGGER = logging.getLogger(__name__)


class AgentRuntime:
    """在服务端管理提示词和工具，仅对外返回助手文本及标准用量字段。"""

    def __init__(
        self, settings: Settings, provider=None,
        tool_executor: Callable[[str, str], dict[str, Any]] = execute_tool,
        context_store=None,
        preference_memory_store=None,
    ) -> None:
        """初始化 Agent 运行时依赖。
        
        参数:
            settings: 服务端的模型供应商配置和执行限制。
            provider: 可选的模型适配器，便于隔离测试。
            tool_executor: 经过校验的工具分发器，不由客户端提供。
            context_store: 可选的 SQLite 工具标识存储，便于隔离测试。
            preference_memory_store: 可选的岗位偏好 SQLite 存储，便于隔离测试。
        """
        self.settings = settings
        self.provider = provider or DeepSeekProvider(settings)
        self.tool_executor = tool_executor
        self.context_store = context_store or ToolContextStore(settings.langgraph_sqlite_path)
        self.preference_memory_store = preference_memory_store or JobPreferenceMemoryStore(
            settings.langgraph_sqlite_path
        )

    def validate_request(self, request: ChatCompletionRequest) -> None:
        """检查对外的 Agent 模型名称及已配置的模型供应商凭证。"""
        if request.model != self.settings.agent_model_name:
            raise AgentError(
                "未知 Agent 模型，请使用 GET /v1/models 查询。",
                "model_not_found", 404, "invalid_request_error", "model",
            )
        self.provider.ensure_configured()

    async def chunks(self, request: ChatCompletionRequest) -> AsyncIterator[dict[str, Any]]:
        """在限定总时长内，逐个返回本次请求的标准响应块。
        
        参数:
            request: 已校验的对话、页面元数据和生成参数。
        """
        trace_input = {
            "messages": [message.model_dump() for message in request.messages],
            "page_context": request.metadata.get("page_context", "applications"),
        }
        with observation(
            self.settings,
            name="handle-chat-turn",
            as_type="agent",
            input=trace_input,
            metadata={"stream": request.stream},
        ) as agent:
            with trace_attributes(
                self.settings,
                session_id=request.metadata.get("conversation_id"),
                tags=["interview-assistant", request.metadata.get("page_context", "applications")],
                metadata={"model_alias": request.model},
            ):
                content: list[str] = []
                finish_reason = None
                try:
                    async with asyncio.timeout(self.settings.agent_timeout_seconds):
                        async with aclosing(self._run(request)) as chunks:
                            async for chunk in chunks:
                                for choice in chunk.get("choices", []):
                                    text = choice.get("delta", {}).get("content")
                                    if text:
                                        content.append(text)
                                    finish_reason = choice.get("finish_reason") or finish_reason
                                yield chunk
                except TimeoutError as exc:
                    update_observation(agent, level="ERROR", status_message="agent_timeout")
                    raise AgentError("Agent 处理超时，请稍后重试。", "agent_timeout", 504) from exc
                except AgentError as exc:
                    update_observation(agent, level="ERROR", status_message=exc.code)
                    raise
                except Exception as exc:
                    update_observation(agent, level="ERROR", status_message=type(exc).__name__)
                    raise
                else:
                    update_observation(agent, output={
                        "content": "".join(content),
                        "finish_reason": finish_reason,
                    })

    async def complete(self, request: ChatCompletionRequest) -> dict[str, Any]:
        """复用 SSE 的执行过程，将响应收集为 chat.completion 对象。"""
        content: list[str] = []
        usage = None
        identity: dict[str, Any] = {}
        app_data: dict[str, Any] = {}
        finish_reason = "stop"
        async with aclosing(self.chunks(request)) as chunks:
            async for chunk in chunks:
                identity = {key: chunk[key] for key in ("id", "created", "model")}
                if chunk.get("app_data"):
                    app_data.update(chunk["app_data"])
                if chunk.get("usage") is not None:
                    usage = chunk["usage"]
                for choice in chunk["choices"]:
                    content.append(choice["delta"].get("content", ""))
                    finish_reason = choice.get("finish_reason") or finish_reason
        response = {
            **identity, "object": "chat.completion",
            "choices": [{"index": 0, "message": {
                "role": "assistant", "content": "".join(content),
            }, "finish_reason": finish_reason}],
        }
        if usage is not None:
            response["usage"] = usage
        if app_data:
            response["app_data"] = app_data
        return response

    async def _run(self, request: ChatCompletionRequest) -> AsyncIterator[dict[str, Any]]:
        """循环执行模型、已校验工具、模型，直到生成最终回答或达到轮次上限。"""
        identity = {
            "id": f"chatcmpl-{uuid4().hex}", "created": int(time()),
            "model": request.model, "object": "chat.completion.chunk",
        }
        include_usage = not request.stream or bool(
            request.stream_options and request.stream_options.include_usage
        )

        def chunk(delta: dict, finish_reason: str | None = None) -> dict:
            """根据助手的增量内容和可选结束原因构建对外响应块。"""
            value = {**identity, "choices": [{
                "index": 0, "delta": delta, "finish_reason": finish_reason,
            }]}
            if include_usage:
                value["usage"] = None
            return value

        page_context = request.metadata.get("page_context", "applications")
        messages = [{
            "role": "system",
            "content": system_prompt(page_context),
        }]
        if page_context == "recommendations":
            preference_summary = await asyncio.to_thread(
                self.preference_memory_store.read_summary
            )
            if preference_summary:
                messages.append({
                    "role": "system",
                    "content": (
                        "用户岗位偏好长期记忆（仅作为推荐依据，不得扩写或虚构）："
                        + preference_summary
                    ),
                })
        context_key = self.context_store.key(request.metadata)
        saved_context = await asyncio.to_thread(self.context_store.read, context_key)
        if saved_context:
            messages.append({"role": "system", "content": "本会话已执行工具返回的标识，可用于继续面试或查询任务；不要向用户展示内部 ID：" + json.dumps(saved_context, ensure_ascii=False)})
        for message in request.messages:
            item = message.model_dump()
            if item["role"] == "developer":
                item["role"] = "system"
            messages.append(item)
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        has_usage = False
        yield chunk({"role": "assistant", "content": ""})
        queried_ids = set()

        for round_index in range(self.settings.agent_max_tool_rounds + 1):
            calls: dict[int, dict[str, Any]] = {}
            content_parts: list[str] = []
            finish_reason = None
            round_usage = None
            async with aclosing(self.provider.stream(
                messages, [QUERY_TOOL, *MUTATION_TOOLS, *BUSINESS_TOOLS], temperature=request.temperature,
                max_tokens=request.max_completion_tokens or request.max_tokens,
            )) as upstream:
                async for event in upstream:
                    if event.get("usage") is not None:
                        round_usage = event["usage"]
                    for choice in event.get("choices", []):
                        if choice.get("index", 0) != 0:
                            continue
                        delta = choice.get("delta", {})
                        # 模型推理内容和内部工具参数不作为公开回复文本返回。
                        text = delta.get("content")
                        if text:
                            content_parts.append(text)
                            yield chunk({"content": text})
                        for call in delta.get("tool_calls", []):
                            index = call.get("index", 0)
                            target = calls.setdefault(index, {
                                "id": "", "type": "function",
                                "function": {"name": "", "arguments": ""},
                            })
                            if call.get("id"):
                                target["id"] = call["id"]
                            for key in ("name", "arguments"):
                                target["function"][key] += call.get("function", {}).get(key) or ""
                        finish_reason = choice.get("finish_reason") or finish_reason
            if round_usage is not None:
                has_usage = True
                for key in usage:
                    usage[key] += int(round_usage.get(key, 0))
            if finish_reason is None:
                raise AgentError("模型响应意外中断，请重试。", "incomplete_provider_response")
            if not calls:
                if finish_reason not in {"stop", "length", "content_filter"}:
                    raise AgentError("模型未正常完成响应，请重试。", "provider_incomplete")
                if not content_parts and finish_reason == "stop":
                    raise AgentError("模型未返回回复内容，请重试。", "empty_provider_response")
                if page_context == "recommendations":
                    await self._refresh_preference_memory(
                        request,
                        "".join(content_parts),
                    )
                yield chunk({}, finish_reason)
                if include_usage and has_usage:
                    yield {**identity, "choices": [], "usage": usage}
                return
            if finish_reason != "tool_calls":
                raise AgentError("工具参数生成不完整，未执行查询。", "incomplete_tool_call")
            if round_index == self.settings.agent_max_tool_rounds or len(calls) > 8:
                raise AgentError("工具调用次数达到上限，请缩小查询范围。", "tool_round_limit", 429)
            tool_calls = [calls[key] for key in sorted(calls)]
            if any(not call["id"] or len(call["function"]["arguments"]) > 16000 for call in tool_calls):
                raise AgentError("模型返回了无效的工具调用。", "invalid_tool_call")
            messages.append({
                "role": "assistant", "content": "".join(content_parts) or None,
                "tool_calls": tool_calls,
            })
            for call in tool_calls:
                function = call["function"]
                try:
                    arguments = json.loads(function["arguments"])
                except ValueError:
                    arguments = None
                with observation(
                    self.settings,
                    name=function["name"] or "unknown-tool",
                    as_type="tool",
                    input=arguments if arguments is not None else function["arguments"],
                ) as tool_observation:
                    try:
                        if not isinstance(arguments, dict):
                            result = {"error": "工具参数必须是 JSON 对象。"}
                        elif function["name"] in {"update_interview", "update_interview_status"} and arguments.get("interview_id") not in queried_ids:
                            result = {"error": "本轮尚未查询该记录，请先调用查询工具并确认唯一目标。"}
                        else:
                            result = await asyncio.to_thread(
                                self.tool_executor, function["name"], function["arguments"],
                            )
                    except Exception as exc:
                        update_observation(
                            tool_observation,
                            level="ERROR",
                            status_message=type(exc).__name__,
                        )
                        raise
                    update_observation(
                        tool_observation,
                        output=result,
                        level="ERROR" if result.get("error") else "DEFAULT",
                        status_message=str(result.get("code") or "tool_error") if result.get("error") else None,
                    )
                if function["name"] == "query_interview_status":
                    queried_ids.update(item["id"] for item in result.get("items", []))
                await asyncio.to_thread(self.context_store.record, context_key, function["name"], result)
                messages.append({
                    "role": "tool", "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                })
                if function["name"] in {"scan_emails", "scan_unread_emails"}:
                    candidates = result.get("result", {}).get("creation_candidates", [])
                    if candidates:
                        yield {
                            **identity,
                            "choices": [],
                            "app_data": {"email_creation_candidates": candidates},
                        }
            if content_parts:
                yield chunk({"content": "\n\n"})

    async def _refresh_preference_memory(
        self,
        request: ChatCompletionRequest,
        assistant_reply: str,
    ) -> None:
        """每新增六个用户轮次，基于该六轮和旧摘要更新岗位偏好记忆。"""
        conversation_key = self.preference_memory_store.conversation_key(request.metadata)
        if conversation_key is None:
            return
        history = [
            message.model_dump()
            for message in request.messages
            if message.role in {"user", "assistant"}
        ]
        history.append({"role": "assistant", "content": assistant_reply})
        user_turns = sum(message["role"] == "user" for message in history)
        summarized_turns = await asyncio.to_thread(
            self.preference_memory_store.read_progress,
            conversation_key,
        )
        target_turns = summarized_turns + 6
        if user_turns < target_turns:
            return
        window = self._preference_window(history, summarized_turns, target_turns)
        previous_summary = await asyncio.to_thread(
            self.preference_memory_store.read_summary
        )
        try:
            result = await self.provider.structured(
                PREFERENCE_MEMORY_INSTRUCTIONS,
                {
                    "previous_summary": previous_summary,
                    "recent_six_turns": window,
                },
                JobPreferenceSummary,
            )
            await asyncio.to_thread(
                self.preference_memory_store.save,
                conversation_key,
                result.summary,
                target_turns,
            )
        except Exception as exc:
            # 记忆是辅助能力；失败不能覆盖或中断已经生成的用户回复。
            LOGGER.warning("job_preference_memory_update_failed error=%s", type(exc).__name__)

    @staticmethod
    def _preference_window(
        messages: list[dict[str, Any]],
        summarized_turns: int,
        target_turns: int,
    ) -> list[dict[str, str]]:
        """提取指定用户轮次及其助手回复，不把系统提示或工具内容交给摘要器。"""
        current_turn = 0
        selected: list[dict[str, str]] = []
        for message in messages:
            role = message.get("role")
            if role == "user":
                current_turn += 1
            if (
                role in {"user", "assistant"}
                and summarized_turns < current_turn <= target_turns
            ):
                selected.append({"role": role, "content": str(message.get("content") or "")})
        return selected
