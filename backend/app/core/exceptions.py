from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.agent.errors import AgentError


class ApplicationError(Exception):
    """可返回给接口调用方的预期业务异常。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: Any = None,
    ) -> None:
        """初始化业务异常。
        
        参数:
            code: 固定的机器可读错误码。
            message: 展示给用户的错误信息。
            status_code: 接口返回的 HTTP 状态码。
            details: 用于排查问题的可选结构化上下文。
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    """构建统一的 JSON 错误响应。
    
    参数:
        request: 当前 HTTP 请求，用于获取请求 ID。
        status_code: 返回给调用方的 HTTP 状态码。
        code: 固定的机器可读错误码。
        message: 展示给用户的错误说明。
        details: 可选的结构化错误详情。
    
    返回值:
        符合服务端统一错误格式的 JSON 响应。
    """
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
                "error": {"code": code, "message": message, "details": details},
                "request_id": getattr(request.state, "request_id", None),
            }
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """注册业务异常和参数校验异常的处理器。
    
    参数:
        app: 需要注册异常处理器的 FastAPI 应用。
    """
    @app.exception_handler(AgentError)
    async def handle_agent_error(request: Request, exc: AgentError) -> JSONResponse:
        """将预期的 Agent 异常转换为 OpenAI 格式的错误响应。"""
        return JSONResponse(status_code=exc.status_code, content=exc.as_dict())

    @app.exception_handler(ApplicationError)
    async def handle_application_error(
        request: Request, exc: ApplicationError
    ) -> JSONResponse:
        """将预期业务异常转换为统一错误响应。"""
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """将请求参数校验失败转换为统一错误响应。"""
        if request.url.path.startswith("/v1/"):
            first = exc.errors()[0]
            param = ".".join(str(part) for part in first["loc"] if part != "body") or None
            error = AgentError(
                "请求参数校验失败，请检查 messages、model 和扩展参数。",
                "invalid_request", 400, "invalid_request_error", param,
            )
            return JSONResponse(status_code=400, content=error.as_dict())
        return _error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数校验失败",
            details=exc.errors(),
        )
