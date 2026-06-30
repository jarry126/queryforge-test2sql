# 开源说明

QueryForge 是一个面向生产实践的通用 Text-to-SQL 项目，目标是把自然语言问题转成安全、可执行、可观测的 SQL 查询链路。

## 项目做了什么

- 用 FastAPI 提供单轮查询、多轮会话、登录注册、文档入库等接口。
- 用 LangGraph 编排 Text-to-SQL 链路：问题改写、检索、schema linking、SQL 生成、校验、执行、自纠错、回答生成。
- 用 pgvector + pg_jieba / Elasticsearch 做混合检索，支持 schema、few-shot、业务文档三类语料。
- 用 sqlglot 做 SQL Guard，只允许安全的单条 SELECT。
- 用只读数据库账号、只读事务、超时和行数限制保护业务数据库。
- 用 Redis 做精确缓存、限流存储和分布式在途并发控制。
- 用 Langfuse 观察单条请求链路，用 Prometheus/Grafana 观察整体服务指标。
- 提供 CSpider 执行准确率评测、公平 A/B、RAG 消融、schema 风格对照、压测与限流测试脚本。

## 已做验证

- 纯逻辑单测：SQL Guard、schema corpus、语言识别、错误分类、文档切块等。
- 端到端冒烟：CSpider schema + few-shot 入库后请求 `/api/v1/query`。
- 准确率实验：noRAG vs RAG、公平 retry 对照、RAG 消融。
- schema 描述增强实验：basic schema vs enriched schema。
- 生产模拟：Docker Compose 启动 app/postgres/redis/prometheus/grafana/langfuse。
- 容错与保护：slowapi 限流、全局限流、LLM 并发闸、Redis 分布式 inflight、熔断器。
- 可观测：`/metrics/` 暴露 `qf_*` 指标，Grafana dashboard 可展示 QPS、时延、SQL 成功率、缓存命中率、检索时延等。

详细实验结果见 [EXPERIMENTS.md](EXPERIMENTS.md)。

## 阶段结论

- few-shot 是当前最稳定的 RAG 收益来源。
- schema 是基础能力，但 schema 描述增强不能盲目上线，必须按库离线 A/B。
- query expansion、业务文档上下文、retry 都不是稳定正收益，默认应该保守关闭或限制使用。
- RAGAS 可以作为检索质量辅助分析，但 Text-to-SQL 的主指标应该是 Execution Accuracy。
- 生产化不只是准确率，还包括 SQL 安全、只读执行、限流、并发控制、缓存、配置校验、可观测和部署可复现。

## 开源前安全注意

- 不要提交 `.env`、`.env.local`、真实 API key、真实数据库密码、Langfuse secret。
- 不要提交本地日志、缓存、`__pycache__`、`.pytest_cache`、`.ruff_cache`、IDE 配置。
- CSpider 原始数据来自 [taolusi/chisp](https://github.com/taolusi/chisp)，请按其许可自行下载，项目不内置数据集。
- 生产部署请使用 `.env.production.example` 作为模板，通过环境变量或密钥管理系统注入真实配置。

## 欢迎贡献

欢迎提交 issue / PR，尤其是：

- 新数据库上的评测结果。
- SQL 错误归因和 case study。
- 更好的 schema linking / few-shot 选择策略。
- 更完善的生产监控指标。
- 真实业务库只读执行的最佳实践。
- 文档、部署脚本、测试覆盖率改进。
