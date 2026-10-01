"""Agent 对外接口：OpenAI Chat Completions 格式的 JSON 和 SSE 响应。"""

import json
import logging
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.app.agent.errors import AgentError
from backend.app.agent.runtime import AgentRuntime
from backend.app.core.config import get_settings
from backend.app.schemas.chat import ChatCompletionRequest

router = APIRouter(prefix="/v1", tags=["Agent (OpenAI compatible)"])
logger = logging.getLogger(__name__)


def get_agent_runtime() -> AgentRuntime:
    """使用服务端 DeepSeek 配置创建本次请求的运行时。"""
    return AgentRuntime(get_settings())


@router.get("/models")
def list_models() -> dict:
    """返回固定的 Agent 模型别名，不依赖上游实际模型名称。"""
    return {"object": "list", "data": [{
        "id": get_settings().agent_model_name, "object": "model",
        "created": 0, "owned_by": "interview-assistant",
    }]}


@router.post("/chat/completions", response_model=None)
async def create_chat_completion(
    request: ChatCompletionRequest,
    runtime: Annotated[AgentRuntime, Depends(get_agent_runtime)],
):
    """使用 OpenAI 兼容的文本对话协议执行一轮 Agent 请求。
    
    参数:
        request: 对话消息、模型别名、当前页面元数据和流式选项。
        runtime: 服务端维护的提示词、模型适配器和已校验的工具分发器。
    
    返回值:
        chat.completion JSON 对象，或 SSE 格式的 chat.completion.chunk 事件。
    """
    runtime.validate_request(request)
    if not request.stream:
        try:
            return await runtime.complete(request)
        except AgentError:
            raise
        except Exception as exc:
            logger.error("agent_failed exception_type=%s", type(exc).__name__)
            raise AgentError("Agent 处理失败，请稍后重试。", "agent_error", 500) from exc

    async def events():
        """将响应块和错误封装为 SSE 事件，并为已结束的响应流添加结束标记。"""
        try:
            async with aclosing(runtime.chunks(request)) as chunks:
                async for chunk in chunks:
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except AgentError as exc:
            yield f"data: {json.dumps(exc.as_dict(), ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.error("agent_stream_failed exception_type=%s", type(exc).__name__)
            error = AgentError("Agent 处理失败，请稍后重试。", "agent_error", 500)
            yield f"data: {json.dumps(error.as_dict(), ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
