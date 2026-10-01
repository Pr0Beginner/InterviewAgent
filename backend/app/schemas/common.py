from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """健康检查接口返回的服务存活信息。"""
    status: Literal["ok"]
    service: str
    version: str
    environment: str
    timestamp: datetime


class ErrorDetail(BaseModel):
    """单个接口错误的机器可读标识和用户可读说明。"""
    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    """接口统一返回的错误对象。"""
    error: ErrorDetail
    request_id: str | None = None


class ExtensibleRequest(BaseModel):
    """携带可选扩展参数的请求基类，便于后续兼容。"""

    extensions: dict[str, Any] = Field(
        default_factory=dict,
        description="请求扩展参数 Map；未约定的键不影响基础业务字段。",
    )
