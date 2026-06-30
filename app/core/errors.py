"""统一异常分类与友好兜底.

把五花八门的底层异常（上游限流 429、超时/连接失败、熔断打开、未知 bug）归类成
三种对外语义，映射到合适的 HTTP 状态码 + 友好文案（不泄漏内部细节）。

设计为零重依赖：用鸭子类型 + 关键词匹配识别异常，不强依赖 openai/httpx 等库的具体类。
"""

from __future__ import annotations


class AppError(Exception):
    """已分类的应用级错误：带 HTTP 状态码、类别、对用户友好的文案。"""

    def __init__(self, status_code: int, category: str, user_message: str):
        super().__init__(user_message)
        self.status_code = status_code
        self.category = category
        self.user_message = user_message


_RATE_HINTS = ("rate limit", "ratelimit", "throttl", "quota", "too many requests", "429")
_UPSTREAM_HINTS = (
    "timeout", "timed out", "connection", "temporarily", "unavailable",
    "service unavailable", "bad gateway", "gateway timeout", "circuit",
    "502", "503", "504",
)


def _status_of(exc: Exception) -> int | None:
    """尽力从异常里抠出 HTTP 状态码（openai/httpx 等的不同属性）。"""
    v = getattr(exc, "status_code", None)
    if isinstance(v, int):
        return v
    resp = getattr(exc, "response", None)
    if resp is not None:
        v = getattr(resp, "status_code", None)
        if isinstance(v, int):
            return v
    return None


def classify(exc: Exception) -> AppError:
    """把任意异常分类成 AppError。已是 AppError 则原样返回。"""
    if isinstance(exc, AppError):
        return exc

    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    status = _status_of(exc)

    # 1) 限流 / 配额（百炼 Throttling、OpenAI RateLimitError 等）
    if status == 429 or "ratelimit" in name or any(h in msg for h in _RATE_HINTS):
        return AppError(429, "rate_limited", "服务调用过于频繁（上游限流），请稍后再试")

    # 2) 上游不可用 / 超时 / 熔断打开
    if (
        (status is not None and status >= 500)
        or "timeout" in name
        or "connection" in name
        or "circuitopen" in name
        or any(h in msg for h in _UPSTREAM_HINTS)
    ):
        return AppError(503, "upstream_unavailable", "依赖服务暂时不可用，请稍后重试")

    # 3) 其它未知异常
    return AppError(500, "internal_error", "服务内部出现异常，请稍后重试")


def friendly_answer(exc: Exception, request_id: str) -> str:
    """给会话回答用的友好兜底文案，带请求编号便于排查。"""
    return f"{classify(exc).user_message}（编号 {request_id}）"
