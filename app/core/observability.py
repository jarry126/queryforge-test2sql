"""Langfuse 链路追踪.

为 LangGraph 提供 CallbackHandler，把每个节点 / LLM 调用记录为可观测的 trace。
未配置 Langfuse 时返回 None，链路照常运行（优雅降级）。
"""

from __future__ import annotations

import os

from app.core.config import settings
from app.core.logging import logger

_handler = None


def disable_langsmith_tracing() -> None:
    """本项目只使用 Langfuse，显式关闭 LangSmith/LangChain 自动追踪。"""
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGSMITH_TRACING"] = "false"
    for key in (
        "LANGCHAIN_API_KEY",
        "LANGSMITH_API_KEY",
        "LANGCHAIN_ENDPOINT",
        "LANGSMITH_ENDPOINT",
        "LANGCHAIN_PROJECT",
        "LANGSMITH_PROJECT",
    ):
        os.environ.pop(key, None)


disable_langsmith_tracing()


def get_langfuse_handler():
    """返回 Langfuse CallbackHandler（单例）；未启用 / 出错则返回 None（优雅降级）。

    兼容两套 SDK：
    - Langfuse v3/v4：凭证由全局客户端/环境变量提供，`CallbackHandler()` 无参构造（langfuse.langchain）。
    - Langfuse v2：`CallbackHandler(public_key=..., secret_key=..., host=...)`（langfuse.callback）。
    """
    disable_langsmith_tracing()
    global _handler
    if not settings.LANGFUSE_ENABLED:
        return None
    if _handler is not None:
        return _handler
    if not (settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
        logger.warning("langfuse_keys_missing", hint="设置 LANGFUSE_PUBLIC_KEY/SECRET_KEY 后才会上报")
        return None

    # 凭证写入环境变量，供 Langfuse 客户端读取
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.LANGFUSE_PUBLIC_KEY
    os.environ["LANGFUSE_SECRET_KEY"] = settings.LANGFUSE_SECRET_KEY
    os.environ["LANGFUSE_HOST"] = settings.LANGFUSE_HOST

    try:
        try:
            # Langfuse v3/v4
            from langfuse import Langfuse
            from langfuse.langchain import CallbackHandler

            Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
            )
            _handler = CallbackHandler()
        except ImportError:
            # Langfuse v2 回退
            from langfuse.callback import CallbackHandler as V2CallbackHandler

            _handler = V2CallbackHandler(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
            )
        logger.info("langfuse_initialized", host=settings.LANGFUSE_HOST)
    except Exception as e:  # noqa: BLE001
        logger.warning("langfuse_init_failed", error=str(e))
        _handler = None
    return _handler
