"""容错：重试 + 熔断器.

- retry_async: 基于 tenacity 的指数退避重试装饰器，用于包裹 LLM / Embedding / Rerank 等外部调用。
- CircuitBreaker: 轻量熔断器，连续失败达阈值后短路一段时间，避免雪崩拖垮整体链路。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.logging import logger

T = TypeVar("T")


def retry_async(max_attempts: int | None = None):
    """异步重试装饰器（指数退避）。"""
    return retry(
        stop=stop_after_attempt(max_attempts or settings.LLM_MAX_RETRIES),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )


class CircuitOpenError(RuntimeError):
    """熔断器打开时抛出。"""


class CircuitBreaker:
    """轻量熔断器（半开恢复）。

    参数：
        name: 标识，用于日志。
        fail_threshold: 连续失败多少次后打开熔断。
        reset_timeout: 打开后多少秒进入半开尝试。
    """

    def __init__(self, name: str, fail_threshold: int = 5, reset_timeout: float = 30.0):
        self.name = name
        self.fail_threshold = fail_threshold
        self.reset_timeout = reset_timeout
        self._failures = 0
        self._opened_at: float | None = None

    def _allow(self) -> bool:
        if self._opened_at is None:
            return True
        # 超过冷却时间 → 半开，允许一次试探
        if time.monotonic() - self._opened_at >= self.reset_timeout:
            return True
        return False

    async def call(self, fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        if not self._allow():
            raise CircuitOpenError(f"熔断器 {self.name} 处于打开状态")
        try:
            result = await fn(*args, **kwargs)
        except Exception:
            self._failures += 1
            if self._failures >= self.fail_threshold:
                self._opened_at = time.monotonic()
                logger.warning("circuit_opened", name=self.name, failures=self._failures)
            raise
        else:
            if self._opened_at is not None:
                logger.info("circuit_closed", name=self.name)
            self._failures = 0
            self._opened_at = None
            return result


# ---- 命名熔断器注册表（按外部依赖共享一个实例）----
_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(name: str) -> CircuitBreaker:
    """获取/创建一个命名熔断器（llm / embedding / rerank 各一个）。"""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(
            name,
            fail_threshold=settings.CIRCUIT_FAIL_THRESHOLD,
            reset_timeout=settings.CIRCUIT_RESET_SECONDS,
        )
    return _breakers[name]


# ---- LLM 并发闸（全局保护模型 API，避免多用户同时打爆下游）----
_llm_sem: asyncio.Semaphore | None = None


def llm_semaphore() -> asyncio.Semaphore:
    """惰性创建的全局信号量，限制同时进行的 LLM 调用数。"""
    global _llm_sem
    if _llm_sem is None:
        _llm_sem = asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY)
    return _llm_sem


# ---- DashScope 并发闸（embedding + rerank 共享，降低触发上游限流的概率）----
_dashscope_sem: asyncio.Semaphore | None = None


def dashscope_semaphore() -> asyncio.Semaphore:
    """惰性创建的全局信号量，限制同时打到百炼的请求数。"""
    global _dashscope_sem
    if _dashscope_sem is None:
        _dashscope_sem = asyncio.Semaphore(settings.DASHSCOPE_MAX_CONCURRENCY)
    return _dashscope_sem
