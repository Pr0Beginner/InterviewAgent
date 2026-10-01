from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.router import api_router
from backend.app.api.routes.chat import router as chat_router
from backend.app.core.config import get_settings
from backend.app.core.exceptions import register_exception_handlers
from backend.app.core.logging import configure_logging
from backend.app.middleware.request_context import RequestContextMiddleware


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。
    
    返回值:
        已注册中间件、异常处理器和接口路由的 FastAPI 实例。
    """
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)
    application.include_router(api_router, prefix=settings.api_prefix)
    application.include_router(chat_router)
    return application


app = create_app()
