# QueryForge 评测说明

本文档说明项目中的评测目标、指标口径、脚本用法和当前阶段结论。完整实验结果见 [EXPERIMENTS.md](EXPERIMENTS.md)。

## 数据集

当前准确率实验使用 [taolusi/chisp](https://github.com/taolusi/chisp) 提供的 CSpider dev 子集。

本仓库不内置 CSpider 原始数据。使用前需要自行下载，并配置：

```bash
CSPIDER_ROOT=/path/to/CSpider
CSPIDER_DB_DIR=/path/to/CSpider/database
```

## 主指标

Text-to-SQL 的主指标是 **Execution Accuracy**。

也就是：

```text
generated SQL 执行结果 == gold SQL 执行结果
```

原因是 Text-to-SQL 的最终目标不是生成“看起来合理”的回答，而是查询结果正确。

RAGAS 保留为辅助评测，但不作为主指标。RAGAS 更适合文档问答型 RAG，用在这里主要帮助分析检索上下文质量。

## 准备流程

```bash
make install
cp .env.example .env
make infra-up
make migrate
make ingest
```

如果只跑纯逻辑单测，不需要基础设施和 LLM：

```bash
make test
```

## 端到端冒烟

```bash
make smoke
```

用于确认：

- API 能正常调用。
- CSpider schema 已灌库。
- LLM / embedding / rerank 配置可用。
- SQL 可以执行。

## 执行准确率

```bash
python -m eval.ex_eval --limit 100
```

输出：

- 总体准确率。
- easy / medium / hard / extra 分桶准确率。
- 错误样本报告。

## 公平 A/B

```bash
python -m eval.fair_ab_eval --db concert_singer --limit 45
python -m eval.fair_ab_eval --db cre_Doc_Template_Mgt --limit 50
python -m eval.fair_ab_eval --db ALL --limit 100
```

对比：

| 方案 | 含义 |
| --- | --- |
| `noRAG_once` | 不使用 RAG，只生成一次。 |
| `noRAG_retry` | 不使用 RAG，允许自纠错。 |
| `RAG_once` | 使用 RAG，只生成一次。 |
| `RAG_retry` | 使用 RAG，允许自纠错。 |

阶段结果：

| 数据集 | noRAG once | noRAG retry | RAG once | RAG retry |
| --- | ---: | ---: | ---: | ---: |
| `concert_singer` 45 | 0.822 | 0.800 | 0.867 | 0.889 |
| `cre_Doc_Template_Mgt` 50 | 0.860 | 0.880 | 0.940 | 0.940 |
| `ALL` 100 | 0.740 | 0.780 | 0.760 | 0.760 |

结论：

- 单库上 RAG 增益明显。
- 跨库小样本下 RAG 提升变小。
- retry 不是稳定正收益，可能修正错误，也可能改坏正确 SQL。

## RAG 消融

```bash
python -m eval.rag_ablation_eval --db ALL --limit 100
```

对比：

| 方案 | 含义 |
| --- | --- |
| `schema_only` | 只用 schema 检索。 |
| `schema_rerank` | schema 检索 + rerank。 |
| `schema_fewshot` | schema + few-shot。 |
| `schema_fewshot_expand` | schema + few-shot + query expansion。 |
| `full_rag` | schema + few-shot + query expansion + docs。 |

阶段结果：

| 数据集 | schema_only | schema_rerank | schema_fewshot | schema_fewshot_expand | full_rag |
| --- | ---: | ---: | ---: | ---: | ---: |
| `concert_singer` 45 | 0.822 | 0.822 | 0.889 | 0.844 | 0.867 |
| `cre_Doc_Template_Mgt` 50 | 0.880 | 0.900 | 0.960 | 0.960 | 0.900 |
| `ALL` 100 | 0.730 | 0.740 | 0.790 | 0.750 | 0.750 |

结论：

- few-shot 是当前最稳定的收益来源。
- query expansion 收益不稳定，可能引入噪声。
- full RAG 不一定优于 schema + few-shot。
- 业务文档上下文更适合特定业务库，不适合默认在通用 benchmark 中打开。

## Schema 风格对照

先生成可审核的表说明：

```bash
python -m eval.generate_schema_descriptions \
  --db concert_singer \
  --output eval/artifacts/schema_descriptions_concert_singer.json
```

再跑 schema basic vs enriched：

```bash
python -m eval.schema_style_eval \
  --db concert_singer \
  --limit 45 \
  --schema-descriptions eval/artifacts/schema_descriptions_concert_singer.json \
  --keep-style enriched
```

阶段结果：

| 数据集 | 方案 | basic | enriched | diff |
| --- | --- | ---: | ---: | ---: |
| `concert_singer` | schema_fewshot | 0.889 | 0.911 | +0.022 |
| `concert_singer` | full_rag | 0.889 | 0.889 | +0.000 |
| `cre_Doc_Template_Mgt` | schema_fewshot | 0.960 | 0.920 | -0.040 |
| `cre_Doc_Template_Mgt` | full_rag | 0.940 | 0.900 | -0.040 |

结论：

- schema 描述增强不是天然正收益。
- 有的库提升，有的库下降。
- 默认应保留 basic schema。
- enriched schema 必须经过离线 A/B 和人工审核后再上线。

## RAGAS 辅助评测

```bash
python -m eval.ragas_eval --limit 50
```

RAGAS 可以辅助观察：

- context precision
- context recall
- faithfulness
- response relevancy

但它不替代 Execution Accuracy。

## 压测与限流测试

开环压测：

```bash
python -m scripts.loadtest --rps 5 --duration 10
```

限流测试：

```bash
python -m scripts.rate_limit_test --requests 20 --concurrency 20
```

已验证能力：

- slowapi 可以返回 429。
- `QUERY_MAX_INFLIGHT` 超限可以返回 503。
- Redis 分布式 inflight 可用于多实例并发保护。
- Prometheus/Grafana 可以采集和展示 `qf_*` 指标。

## 当前建议默认配置

```bash
QUERY_EXPANSION_ENABLED=false
DOC_CONTEXT_ENABLED=false
FEWSHOT_CROSS_DB=false
SEMANTIC_CACHE_ENABLED=false
```

原因：

- query expansion 当前收益不稳定。
- 业务文档上下文在通用 benchmark 中可能引入噪声。
- 多租户/多库生产场景下 few-shot 跨库可能带来隔离风险。
- 语义近似缓存对 Text-to-SQL 有误命中风险，默认关闭更稳。
