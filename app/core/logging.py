"""应用日志配置与初始化（移植自生产模板，适配 QueryForge 配置）.

使用 structlog 提供结构化日志，所有环境统一 text 格式：
- 本地终端 isatty()=True 自动着色，便于阅读；
- Docker/K8s 容器 isatty()=False 自动关闭颜色，输出纯文本，运维按固定格式拆字段。

日志行格式：
    {时间} - [{env}] - {LEVEL} - [{request_id}] - [{module.func:line}] - {事件}  {参数JSON}

请求级上下文（user_id / session_id 等）通过 ContextVar 绑定，自动出现在该请求的每条日志里；
request_id 来自 asgi-correlation-id 中间件。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from asgi_correlation_id import correlation_id

from app.core.config import settings

settings.LOG_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# ANSI 颜色（仅终端着色；PyCharm 用 PYCHARM_HOSTED 识别）
# ---------------------------------------------------------------------------
_USE_COLORS = sys.stdout.isatty() or bool(os.environ.get("PYCHARM_HOSTED"))
_RESET, _BOLD, _DIM, _GRAY = "\033[0m", "\033[1m", "\033[2m", "\033[90m"
_CYAN, _GREEN, _YELLOW, _RED, _BOLD_RED = "\033[96m", "\033[32m", "\033[33m", "\033[31m", "\033[1;31m"
_LEVEL_COLOR = {"DEBUG": _CYAN, "INFO": _GREEN, "WARNING": _YELLOW, "ERROR": _RED, "CRITICAL": _BOLD_RED}


def _c(text: Any, *codes: str) -> str:
    if not _USE_COLORS or not codes:
        return str(text)
    return "".join(codes) + str(text) + _RESET


# 在控制台 Parameters 段优先展示的业务字段（有序）
READABLE_LOG_FIELD_ORDER = (
    "method", "path", "status_code", "status", "duration_ms",
    "user_id", "session_id", "db_id", "thread_id", "sql",
    "model", "error_type", "error",
)

# 太吵的三方库日志，压到 WARNING
# uvicorn.access：每请求的访问日志，与本项目中间件的"收到请求/请求完成"重复，静音之
NOISY_THIRD_PARTY_LOGGERS = (
    "httpcore", "httpx", "openai", "urllib3", "hpack", "langfuse", "langsmith", "uvicorn.access",
)

_CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# 请求级上下文（ContextVar）
# ---------------------------------------------------------------------------
_request_context: ContextVar[dict[str, Any] | None] = ContextVar("request_context", default=None)


def bind_context(**kwargs: Any) -> None:
    """把上下文字段绑定到当前请求（之后该请求的每条日志都会带上）。"""
    current = _request_context.get() or {}
    _request_context.set({**current, **kwargs})


def clear_context() -> None:
    """清理当前请求的上下文字段（请求结束时调用，避免泄漏到下一个请求）。"""
    _request_context.set(None)


def get_context() -> dict[str, Any]:
    return _request_context.get() or {}


def _add_context(_: Any, __: str, event_dict: dict) -> dict:
    ctx = get_context()
    if ctx:
        event_dict.update(ctx)
    return event_dict


def _add_request_id(_: Any, __: str, event_dict: dict) -> dict:
    if rid := correlation_id.get():
        event_dict["request_id"] = rid
    return event_dict


def _add_environment(_: Any, __: str, event_dict: dict) -> dict:
    event_dict["environment"] = settings.APP_ENV.value
    return event_dict


# ---------------------------------------------------------------------------
# 控制台渲染
# ---------------------------------------------------------------------------
def _format_ts(value: Any) -> str:
    if not value:
        now = datetime.now(_CST)
        return f"{now:%Y-%m-%d %H:%M:%S}.{now.microsecond // 1000:03d}"
    raw = str(value)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(_CST)
        return f"{parsed:%Y-%m-%d %H:%M:%S}.{parsed.microsecond // 1000:03d}"
    except ValueError:
        return raw


def prepare_console_event_dict(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> dict:
    """把零散的业务字段汇总进 parameters，并清理噪声字段。"""
    parameters: dict[str, Any] = {}
    raw = event_dict.get("parameters")
    if isinstance(raw, dict):
        parameters.update(raw)
    for field in READABLE_LOG_FIELD_ORDER:
        v = event_dict.get(field)
        if v is not None and v != "":
            parameters.setdefault(field, v)
    if parameters:
        event_dict["parameters"] = parameters
    for noisy in ("pathname", "filename", "logger", "logger_name"):
        event_dict.pop(noisy, None)
    return dict(event_dict)


def render_text_log(_: Any, method_name: str, event_dict: MutableMapping[str, Any]) -> str:
    """渲染彩色可读 text 日志行。"""
    timestamp = event_dict.pop("timestamp", None)
    environment = event_dict.pop("environment", settings.APP_ENV.value)
    level = str(event_dict.pop("level", method_name)).upper()
    request_id = event_dict.pop("request_id", "-") or "-"
    module = event_dict.pop("module", None) or "app"
    func_name = event_dict.pop("func_name", None)
    lineno = event_dict.pop("lineno", None)
    event = event_dict.pop("event", "")
    parameters = event_dict.pop("parameters", None)

    location = str(module)
    if func_name and lineno:
        location = f"{location}.{func_name}:{lineno}"
    elif lineno:
        location = f"{location}:{lineno}"

    level_color = _LEVEL_COLOR.get(level, "")
    is_severe = level in ("ERROR", "CRITICAL")
    segments = [
        _c(_format_ts(timestamp), _GRAY),
        _c(f"[{environment}]", _GRAY),
        _c(f"{level:<8}", level_color, _BOLD if is_severe else ""),
        _c(f"[{request_id}]", _CYAN),
        _c(f"[{location}]", _DIM),
        _c(str(event), (_BOLD + level_color) if is_severe else (level_color if level == "WARNING" else "")),
    ]
    line = " - ".join(segments)

    if parameters:
        line = f"{line}  {_c(json.dumps(parameters, ensure_ascii=False, default=str), _YELLOW)}"

    for field in READABLE_LOG_FIELD_ORDER:
        event_dict.pop(field, None)
    remaining = {k: v for k, v in event_dict.items() if v not in (None, "", {})}
    if remaining:
        line = f"{line}  {_c(json.dumps(remaining, ensure_ascii=False, default=str), _GRAY)}"
    return line


def setup_logging() -> None:
    """配置 structlog（统一 text 格式 + 请求上下文 + 代码位置）。"""
    log_level = logging.DEBUG if settings.DEBUG else getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    logging.basicConfig(format="%(message)s", level=log_level, handlers=[handler], force=True)

    for name in NOISY_THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            _add_context,
            _add_request_id,
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                    structlog.processors.CallsiteParameter.MODULE,
                }
            ),
            _add_environment,
            prepare_console_event_dict,
            render_text_log,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


setup_logging()
logger = structlog.get_logger("queryforge")
