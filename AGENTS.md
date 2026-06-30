DO NOT send optional commentary
# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

QueryForge 是生产级通用 Text-to-SQL（NL2SQL）服务：FastAPI + LangGraph + RAG，把自然语言转成安全可执行的 SQL。代码注释与文档以中文为主。

## 常用命令

```bash
make install        # pip install -e ".[eval,dev]"（ES 后端额外 .[es]）
make infra-up       # docker compose 起 postgres(pgvector+pg_jieba)/redis/prometheus/grafana
make migrate        # alembic upgrade head（建扩展与表，含 query_cache）
make ingest         # 把 CSpider schema + few-shot 灌进 pgvector（python -m eval.ingest_cspider）
make run            # uvicorn app.main:app --reload
make test           # pytest，纯逻辑单测，无需基础设施/LLM
make smoke          # CSpider dev 抽样端到端冒烟（需 LLM + 已灌库）
make loadtest       # 100 QPS 开环压测 /query
make lint / fmt     # ruff check / format
```

评测：`python -m eval.ex_eval --limit 100`（执行准确率，按难度分桶）、`python -m eval.ragas_eval --limit 50`（ragas）。

**跑单个测试**：`pytest tests/test_guard.py -q` 或 `pytest tests/test_guard.py::test_empty_rejected`。
`tests/` 全部是纯逻辑单测（guard / schema_corpus / 切块 / hardness），不依赖 DB、LLM 或基础设施，可直接跑；`smoke` 和 `eval/*` 才需要完整安装 + 灌库 + API key。

## 架构大局（需跨文件理解的部分）

**请求主路径**：`api/v1/query.py` → `services/text2sql.py` → `core/langgraph/graph.py` → `sql/`。
`text2sql.run_query` 是 API 与图之间的薄封装，**两层缓存短路在这里**：先 Redis 精确缓存（`core/cache.py`），再 pgvector 语义近似缓存（`core/semantic_cache.py`），都未命中才进图；成功结果同时回写两层。

**LangGraph 链路**（`core/langgraph/graph.py` 是中枢，节点在 `core/langgraph/nodes/`）：
`detect_language → rewrite → expand → retrieve →(无上下文)error_node | schema_linking → generate_sql → validate_sql → execute_sql → format_answer`。
两个条件路由 + **自纠错环路**：`validate_sql`/`execute_sql` 失败时，若 `attempt < SQL_MAX_RETRY` 回到 `generate_sql`（携带上次错误重生成），否则进 `format_answer` 返回失败。改链路结构只动 `graph.py` 的 `_route_*` 函数和 `add_*edge`；节点只返回状态增量（`GraphState`，`total=False`）。

**RAG 检索三套语料 + 混合检索**（`core/rag/`）：
- 三张表：`schema_doc`（schema linking 用）、`fewshot_example`（NL→SQL 示例）、`rag_chunk`（业务文档）。
- `retriever.hybrid_search`：向量（`vectorstore`，pgvector cosine）+ 关键词（后端由 `RETRIEVAL_BACKEND` 选 `keyword.py`/pg_jieba 或 `es_keyword.py`/Elasticsearch，ES 失败自动回退 pg）→ RRF 融合 → Qwen gte-rerank 重排（`reranker`，DashScope 原生 API）。
- **LLM 与向量是两套独立 endpoint**：LLM 走 OpenAI（`OPENAI_*` + `LLM_MODEL`，GPT）；embedding/rerank 走阿里云百炼 DashScope（`DASHSCOPE_API_KEY` + `EMBEDDING_BASE_URL`/`RERANK_BASE_URL`，Qwen `text-embedding-v4` / `gte-rerank-v2`）。`embeddings.py` 经 OpenAI 兼容接口、按 `EMBEDDING_BATCH_SIZE` 分批；`reranker.py` 用 httpx 调原生 REST。
- **非显然**：`doc_retriever.retrieve_docs` 实现 summary 特殊展开——命中 summary 块后不用其文本，而是读 `metadata.chunk_ids` 回表取回整页原文（对应设计图）。文档入库的 chunk_id 集合由 `services/ingest.py` 写入。

**SQL 安全是强制闸门**：`sql/guard.py` 用 sqlglot 解析，仅放行单条 SELECT、禁 DDL/DML、自动注入 LIMIT；`sql/executor.py` 只读沙箱执行，按 `SQL_DIALECT` 走 sqlite（CSpider 的 `database/<db_id>/<db_id>.sqlite`）或 postgres（`statement_timeout` + 只读事务）。

**CSpider 是数据源**：`eval/cspider_loader.py` 读 tables.json/dev.json/gold；`schema_corpus.py` 把 schema dict 转成可检索文档 + DDL 文本。生产换库可用 `sql/schema_introspect.py` 从 sqlite 反查 schema。

**Web 应用路径（登录 + 多轮会话）**：原生单页前端在 `static/`（`main.py` 挂到 `/ui`，零构建）。鉴权用 JWT（`core/security.py` + `api/deps.py` 的 `get_current_user`），`api/v1/auth.py` 注册/登录。会话与消息在 `api/v1/sessions.py` + `services/session_store.py`，表 `app_user / chat_session / chat_message`（迁移 0003）。**多轮关键**：`/sessions/{id}/chat` 从 `chat_message` 表读历史作为上下文传入 `run_query`（DB 是历史唯一真相来源，不依赖 LangGraph checkpointer），因此带历史的请求会自动跳过缓存。注意 `api/v1/query.py` 是**无鉴权的单轮接口**，供 eval/smoke 直接用，与会话路径并存。

## 贯穿全局的约定

- **配置驱动，换组件不改代码**：LLM 模型（`LLM_MODEL`，走 langchain-openai）、embedding/维度、检索后端、缓存阈值全在 `core/config.py`（pydantic-settings）+ `.env`。**`EMBEDDING_DIM` 必须与 alembic 建表/HNSW 索引维度一致**，改维度要重建迁移。
- **优雅降级**：Redis、Langfuse、Qwen rerank、Elasticsearch、语义缓存在未配置/出错时一律降级为 no-op 或回退，不阻断主链路——调试时注意"功能静默跳过"可能是降级而非 bug。
- **外部调用包熔断 + 重试**：LLM/embedding/rerank 经 `core/resilience.py` 的 `get_breaker()` + `retry_async()`；新增外部依赖应沿用此模式。
- **可观测**：Prometheus 指标在 `core/metrics.py`（`qf_*`，挂 `/metrics`），结构化日志用 structlog + correlation-id，Langfuse handler 通过图 config 注入。
- **alembic env** 用应用配置 DSN 并替换为 `postgresql+psycopg://`；迁移里直接 `op.execute` 原生 SQL 建 vector/tsvector 列与索引。
