from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """返回已配置 MySQL 连接的缓存 SQLAlchemy 引擎。"""
    settings = get_settings()
    return create_engine(
        settings.mysql_url,
        echo=settings.mysql_echo,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """返回用于创建请求级数据库会话的缓存工厂。"""
    return sessionmaker(
        bind=get_engine(),
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


def get_db_session() -> Generator[Session, None, None]:
    """提供 SQLAlchemy 会话，并在请求结束后关闭。
    
    逐次产出:
        连接 MySQL 的请求级 SQLAlchemy 会话。
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
