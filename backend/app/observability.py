"""可选的 Langfuse 观测层；观测失败不得改变业务执行结果。"""

from __future__ import annotations

import logging
import re
import sys
from contextlib import contextmanager
from threading import Lock
from typing import Any, Iterator

from langfuse import Langfuse, propagate_attributes

from backend.app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)
_CLIENT_LOCK = Lock()
_CLIENT: Langfuse | None = None
_CLIENT_SIGNATURE: tuple[Any, ...] | None = None
_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|secret|password|authorization|cookie|token|auth[_-]?code)",
    re.IGNORECASE,
)
_SAFE_SCALARS = {
    "status", "code", "source", "page", "page_size", "total", "has_next",
    "success_count", "failed_count", "imported_count", "exported_count",
    "scanned", "updated", "ignored", "already_processed", "finish_reason",
}


def _credentials(settings: Settings) -> tuple[str, str] | None:
    """启用且密钥完整时返回凭据，否则保持无观测模式。"""
    secret = settings.langfuse_secret_key
    secret_value = secret.get_secret_value().strip() if secret else ""
    public_value = (settings.langfuse_public_key or "").strip()
    if not settings.langfuse_enabled or not public_value or not secret_value:
        return None
    return public_value, secret_value


def get_langfuse(settings: Settings | None = None) -> Langfuse | None:
    """按进程复用一个客户端；配置不完整或初始化失败时返回 None。"""
    global _CLIENT, _CLIENT_SIGNATURE
    settings = settings or get_settings()
    credentials = _credentials(settings)
    if credentials is None:
        return None
    signature = (
        *credentials,
        settings.langfuse_base_url,
        settings.langfuse_environment,
        settings.langfuse_sample_rate,
        settings.langfuse_capture_content,
    )
    with _CLIENT_LOCK:
        if _CLIENT is not None and _CLIENT_SIGNATURE == signature:
            return _CLIENT
        try:
            if _CLIENT is not None:
                _CLIENT.shutdown()
            _CLIENT = Langfuse(
                public_key=credentials[0],
                secret_key=credentials[1],
                base_url=settings.langfuse_base_url,
                environment=settings.langfuse_environment,
                release=settings.app_version,
                sample_rate=settings.langfuse_sample_rate,
                mask=lambda *, data, **_: observation_data(settings, data),
                tracing_enabled=True,
            )
            _CLIENT_SIGNATURE = signature
            return _CLIENT
        except Exception as exc:  # 观测系统不能阻塞主业务。
            _CLIENT = None
            _CLIENT_SIGNATURE = None
            logger.warning("langfuse_initialization_failed exception_type=%s", type(exc).__name__)
            return None


def _bounded(value: Any, *, depth: int = 0) -> Any:
    """递归移除凭据并限制观测载荷大小。"""
    if depth >= 6:
        return "[truncated]"
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:100]:
            name = str(key)
            result[name] = "[redacted]" if _SECRET_KEY.search(name) else _bounded(item, depth=depth + 1)
        if len(value) > 100:
            result["_truncated_keys"] = len(value) - 100
        return result
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        result = [_bounded(item, depth=depth + 1) for item in items[:100]]
        if len(items) > 100:
            result.append({"_truncated_items": len(items) - 100})
        return result
    if isinstance(value, str):
        return value if len(value) <= 16000 else value[:16000] + "…[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if hasattr(value, "model_dump"):
        return _bounded(value.model_dump(mode="json"), depth=depth + 1)
    return _bounded(str(value), depth=depth + 1)


def summarize(value: Any) -> Any:
    """生成不包含业务正文的结构摘要，用作默认观测载荷。"""
    if isinstance(value, dict):
        summary: dict[str, Any] = {"keys": sorted(str(key) for key in value)[:100]}
        for key, item in value.items():
            if key in _SAFE_SCALARS and (item is None or isinstance(item, (bool, int, float, str))):
                summary[key] = item
            elif isinstance(item, (list, tuple, set)):
                summary[f"{key}_count"] = len(item)
            elif isinstance(item, str):
                summary[f"{key}_characters"] = len(item)
        return summary
    if isinstance(value, (list, tuple, set)):
        return {"type": "list", "count": len(value)}
    if isinstance(value, str):
        return {"type": "text", "characters": len(value)}
    return {"type": type(value).__name__}


def observation_data(settings: Settings, value: Any) -> Any:
    """按隐私开关返回受限正文或仅返回结构摘要。"""
    # Langfuse 用 None 表示“本次 update 未提供该字段”；必须原样保留，
    # 否则 mask 会把它变成非空摘要并覆盖先前已经记录的 input/output。
    if value is None:
        return None
    return _bounded(value) if settings.langfuse_capture_content else summarize(value)


@contextmanager
def observation(
    settings: Settings,
    *,
    name: str,
    as_type: str = "span",
    input: Any = None,
    metadata: dict[str, Any] | None = None,
    model: str | None = None,
    model_parameters: dict[str, Any] | None = None,
) -> Iterator[Any | None]:
    """创建一个不会因初始化或关闭失败而破坏业务的 observation。"""
    client = get_langfuse(settings)
    if client is None:
        yield None
        return
    try:
        manager = client.start_as_current_observation(
            name=name,
            as_type=as_type,
            input=input,
            metadata=metadata,
            model=model,
            model_parameters=model_parameters,
        )
        current = manager.__enter__()
    except Exception as exc:
        logger.warning("langfuse_observation_start_failed name=%s exception_type=%s", name, type(exc).__name__)
        yield None
        return
    try:
        yield current
    except BaseException:
        error = sys.exc_info()
        try:
            manager.__exit__(*error)
        except Exception as exc:
            logger.warning("langfuse_observation_close_failed name=%s exception_type=%s", name, type(exc).__name__)
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception as exc:
            logger.warning("langfuse_observation_close_failed name=%s exception_type=%s", name, type(exc).__name__)


@contextmanager
def trace_attributes(
    settings: Settings,
    *,
    session_id: str | None,
    tags: list[str],
    metadata: dict[str, Any] | None = None,
) -> Iterator[None]:
    """向当前 Trace 传播会话属性；失败时退化为无属性观测。"""
    if get_langfuse(settings) is None:
        yield
        return
    try:
        manager = propagate_attributes(session_id=session_id, tags=tags, metadata=metadata)
        manager.__enter__()
    except Exception as exc:
        logger.warning("langfuse_attributes_start_failed exception_type=%s", type(exc).__name__)
        yield
        return
    try:
        yield
    finally:
        try:
            manager.__exit__(None, None, None)
        except Exception as exc:
            logger.warning("langfuse_attributes_close_failed exception_type=%s", type(exc).__name__)


def update_observation(current: Any | None, **values: Any) -> None:
    """安全更新 observation，不把遥测异常暴露给调用者。"""
    if current is None:
        return
    try:
        current.update(**values)
    except Exception as exc:
        logger.warning("langfuse_observation_update_failed exception_type=%s", type(exc).__name__)


def shutdown_observability() -> None:
    """进程关闭时刷新后台队列。"""
    global _CLIENT, _CLIENT_SIGNATURE
    with _CLIENT_LOCK:
        client, _CLIENT, _CLIENT_SIGNATURE = _CLIENT, None, None
    if client is not None:
        try:
            client.shutdown()
        except Exception as exc:
            logger.warning("langfuse_shutdown_failed exception_type=%s", type(exc).__name__)
