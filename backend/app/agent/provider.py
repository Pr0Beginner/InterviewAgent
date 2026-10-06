"""使用 OpenAI Python SDK 调用 DeepSeek 的适配器。"""

from collections.abc import AsyncIterator
from typing import Any
import asyncio
import json

from pydantic import ValidationError

from openai import (
    APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI,
    AuthenticationError, RateLimitError, DefaultAsyncHttpxClient,
)

from backend.app.agent.errors import AgentError
from backend.app.core.config import Settings
from backend.app.observability import get_langfuse


class DeepSeekProvider:
    """创建模型响应流；模型供应商配置不从用户消息中获取。"""

    def __init__(self, settings: Settings) -> None:
        """保存服务端配置，其中 API 密钥使用 SecretStr 封装。"""
        self.settings = settings

    def ensure_configured(self) -> None:
        """缺少 API 密钥时，在开始 SSE 响应前返回明确错误。"""
        key = self.settings.deepseek_api_key
        if key is None or not key.get_secret_value().strip():
            raise AgentError(
                "请先在 backend/.env 配置 DEEPSEEK_API_KEY，再重启服务端。",
                "provider_not_configured", 503,
            )

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
        *, temperature: float | None, max_tokens: int | None,
        response_format: dict | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """逐个返回模型原始响应块，取消请求时关闭连接。
        
        参数:
            messages: 对话消息及服务端工具执行结果。
            tools: 允许模型调用的函数定义列表。
            temperature: 客户端传入的可选采样温度。
            max_tokens: 单次模型调用的可选输出令牌数上限。
            response_format: 结构化任务所需的可选 JSON 输出格式。
        """
        self.ensure_configured()
        options: dict[str, Any] = {}
        if response_format is not None:
            options["response_format"] = response_format
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["max_tokens"] = max_tokens
        completion_options: dict[str, Any] = {}
        client_class = AsyncOpenAI
        if get_langfuse(self.settings) is not None:
            # 官方包装器是 OpenAI SDK 的 drop-in replacement，会自动记录流式
            # generation、首 token 延迟、用量、成本和异常，并继承当前 Agent trace。
            from langfuse.openai import AsyncOpenAI as LangfuseAsyncOpenAI

            client_class = LangfuseAsyncOpenAI
            completion_options.update({
                "name": "generate-agent-response",
                "metadata": {"provider": "deepseek", "feature": "agent-chat"},
                "langfuse_public_key": self.settings.langfuse_public_key,
            })
        try:
            async with client_class(
                api_key=self.settings.deepseek_api_key.get_secret_value(),
                base_url=self.settings.deepseek_base_url,
                timeout=self.settings.agent_timeout_seconds,
                max_retries=0,
                http_client=DefaultAsyncHttpxClient(trust_env=False),
            ) as client:
                stream = await client.chat.completions.create(
                    model=self.settings.deepseek_model,
                    messages=messages, tools=tools, stream=True,
                    stream_options={"include_usage": True},
                    extra_body={"thinking": {"type": "disabled"}},
                    **options,
                    **completion_options,
                )
                async with stream:
                    async for chunk in stream:
                        yield chunk.model_dump(exclude_none=True)
        except AuthenticationError as exc:
            raise AgentError("DeepSeek 密钥无效，请检查服务端配置。", "provider_auth_error") from exc
        except RateLimitError as exc:
            raise AgentError("DeepSeek 请求过于频繁，请稍后重试。", "rate_limit_exceeded", 429) from exc
        except APITimeoutError as exc:
            raise AgentError("DeepSeek 响应超时，请稍后重试。", "provider_timeout", 504) from exc
        except APIConnectionError as exc:
            raise AgentError("无法连接 DeepSeek，请检查网络和服务端地址。", "provider_unreachable") from exc
        except APIStatusError as exc:
            raise AgentError("DeepSeek 请求失败，请检查账户额度和模型配置。", "provider_error") from exc

    async def structured(self, instructions: str, data: dict, schema):
        """为 Skill 或邮件提取器生成并校验 JSON 数据。
        
        参数:
            instructions: 服务端定义的任务指令。
            data: 不可信的用户或外部来源数据，与指令分开序列化。
            schema: 用于校验输出的 Pydantic 模型。
        """
        prompt = instructions + "\n只输出 JSON，满足如下 JSON Schema：" + json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps(data, ensure_ascii=False)}]
        try:
            async with asyncio.timeout(self.settings.agent_timeout_seconds):
                text = ""
                finished = None
                async for event in self.stream(messages, [], temperature=0.3, max_tokens=4000,
                                                response_format={"type": "json_object"}):
                    for choice in event.get("choices", []):
                        text += choice.get("delta", {}).get("content") or ""
                        finished = choice.get("finish_reason") or finished
                if finished != "stop":
                    raise AgentError("模型结构化结果不完整，请重试。", "incomplete_structured_output")
                return schema.model_validate_json(text)
        except ValidationError as exc:
            raise AgentError("模型返回的数据不符合业务格式，请重试。", "invalid_structured_output") from exc
        except TimeoutError as exc:
            raise AgentError("模型处理超时，请重试。", "provider_timeout", 504) from exc
