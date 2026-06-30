"""Prometheus 指标.

暴露 text-to-SQL 链路的关键指标，配合 Grafana 监控：
- 请求量 / 时延（按结果）
- LLM 调用时延
- 检索时延 / 命中
- SQL 执行结果（成功 / 失败 / 自纠错次数）
- 缓存命中率
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram, make_asgi_app

# ---- HTTP / 链路 ----
query_requests_total = Counter(
    "qf_query_requests_total", "Text-to-SQL 请求总数", ["status"]
)
query_latency_seconds = Histogram(
    "qf_query_latency_seconds", "端到端查询时延", ["status"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32),
)

# ---- LLM ----
llm_latency_seconds = Histogram(
    "qf_llm_latency_seconds", "LLM 调用时延", ["node"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32),
)
llm_calls_total = Counter("qf_llm_calls_total", "LLM 调用次数", ["node", "status"])

# ---- 检索 ----
retrieval_latency_seconds = Histogram(
    "qf_retrieval_latency_seconds", "检索时延", ["channel"],
)

# ---- SQL ----
sql_exec_total = Counter("qf_sql_exec_total", "SQL 执行结果", ["status"])
sql_self_correct_total = Counter("qf_sql_self_correct_total", "SQL 自纠错触发次数")

# ---- 缓存 ----
cache_total = Counter("qf_cache_total", "缓存访问", ["result"])  # hit | miss

# ASGI 子应用：挂到 /metrics
metrics_app = make_asgi_app()
