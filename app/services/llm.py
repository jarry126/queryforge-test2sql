"""LLM 服务.

封装 langchain-openai 的 ChatOpenAI。模型名 / base_url / key 全部来自配置，
换模型（GPT-5.4 -> 其它）或换 OpenAI 兼容端点（vLLM、DashScope）只改 .env。
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.observability import disable_langsmith_tracing
from app.core.resilience import get_breaker, llm_semaphore, retry_async

disable_langsmith_tracing()


@lru_cache
def get_llm(temperature: float | None = None, json_mode: bool = False) -> ChatOpenAI:
    """返回（缓存的）ChatOpenAI 实例。

    参数：
        temperature: 覆盖默认温度（确定性任务如生成 SQL 用 0）。
        json_mode: 是否强制 JSON 输出（用于结构化节点）。
    """
    kwargs: dict = {
        "model": settings.LLM_MODEL,
        "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "timeout": settings.LLM_TIMEOUT_SECONDS,
        "api_key": settings.OPENAI_API_KEY,
        "base_url": settings.OPENAI_BASE_URL,
        "max_retries": 0,  # 重试交给 tenacity 统一控制
    }
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    disable_langsmith_tracing()
    return ChatOpenAI(**kwargs)


@retry_async()
async def _ainvoke_once(messages: list[BaseMessage], temperature: float | None, json_mode: bool) -> str:
    llm = get_llm(temperature=temperature, json_mode=json_mode)
    resp = await llm.ainvoke(messages)
    return resp.content if isinstance(resp.content, str) else str(resp.content)


async def ainvoke(messages: list[BaseMessage], temperature: float | None = None, json_mode: bool = False) -> str:
    """调用 LLM 并返回纯文本内容（熔断器 + 重试）。"""
    async with llm_semaphore():
        return await get_breaker("llm").call(_ainvoke_once, messages, temperature, json_mode)
