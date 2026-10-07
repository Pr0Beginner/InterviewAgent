"""OpenAI Chat Completions 请求协议中的文本对话子集。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatMessage(BaseModel):
    """单条文本消息；内部工具消息由 Agent 管理。"""

    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "developer", "user", "assistant"] = Field(
        description="消息角色；工具调用与工具结果由服务端内部管理。"
    )
    content: str = Field(min_length=1, max_length=32000, description="消息正文。")


class StreamOptions(BaseModel):
    """对外 SSE 响应的配置选项。"""

    model_config = ConfigDict(extra="forbid")
    include_usage: bool = Field(default=False, description="结束前额外返回 token 用量块。")


class RecommendationPageState(BaseModel):
    """推荐岗位页当前可见筛选条件，只作为 Agent 的默认上下文。"""

    model_config = ConfigDict(extra="forbid")
    cities: list[str] = Field(default_factory=list, max_length=10)
    work_experience: Literal["不限", "应届生", "1年以内", "1-3年", "3-5年", "5-10年", "10年以上"] = "应届生"
    keywords: list[str] = Field(default_factory=list, max_length=20)
    search_id: str | None = Field(default=None, max_length=80)
    result_count: int = Field(default=0, ge=0, le=10000)

    @model_validator(mode="after")
    def validate_text_lengths(self) -> "RecommendationPageState":
        if any(not value.strip() or len(value) > 80 for value in [*self.cities, *self.keywords]):
            raise ValueError("页面筛选项必须为 1 到 80 个字符")
        return self


class ChatCompletionRequest(BaseModel):
    """受支持的 OpenAI 参数及应用扩展 Map。"""

    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, description="Agent 对外模型名：interview-assistant。")
    messages: list[ChatMessage] = Field(
        min_length=1, max_length=100, description="按时间顺序传入完整对话历史。"
    )
    stream: bool = Field(default=False, description="true 使用 SSE，false 返回完整 JSON。")
    stream_options: StreamOptions | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=32768)
    metadata: dict[str, str] = Field(
        default_factory=dict,
        max_length=16,
        description="字符串 Map；page_context 指定当前 Tab，conversation_id 用于关联会话。",
    )
    extensions: dict[str, Any] = Field(
        default_factory=dict, description="项目扩展 Map，不透传给模型供应商。"
    )

    @model_validator(mode="after")
    def validate_conversation(self) -> "ChatCompletionRequest":
        """向 DeepSeek 发送请求前，拒绝不支持的参数组合。"""
        if self.messages[-1].role != "user":
            raise ValueError("最后一条消息必须是 user 消息")
        if self.stream_options is not None and not self.stream:
            raise ValueError("stream_options 仅能与 stream=true 一起使用")
        if self.max_tokens is not None and self.max_completion_tokens is not None:
            raise ValueError("max_tokens 与 max_completion_tokens 只能设置一个")
        if self.metadata.get("page_context", "applications") not in {
            "applications", "recommendations", "mock_interview"
        }:
            raise ValueError("不支持的 page_context")
        if any(len(key) > 64 or len(value) > 512 for key, value in self.metadata.items()):
            raise ValueError("metadata 的键最多 64 字符，值最多 512 字符")
        if sum(len(message.content) for message in self.messages) > 128000:
            raise ValueError("对话历史过长，请开始新对话")
        if "page_state" in self.extensions:
            RecommendationPageState.model_validate(self.extensions["page_state"])
        return self
