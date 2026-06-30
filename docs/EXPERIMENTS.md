# QueryForge 实验记录与阶段结论

本文档记录当前阶段对 QueryForge Text-to-SQL 的主要评测。实验目标不是证明某个 RAG 配置永远最好，而是用可复现实验回答几个工程问题：

- RAG 对 Text-to-SQL 是否真的有帮助？
- RAG 中到底是哪一部分带来收益？
- schema 描述增强是否应该默认开启？
- query expansion、业务文档上下文、retry 是否稳定提升？

## 评测口径

- 数据集：[taolusi/chisp](https://github.com/taolusi/chisp) 提供的 CSpider dev 子集。本仓库不内置 CSpider 原始数据，请按原项目许可自行下载。
- 主指标：Execution Accuracy，即生成 SQL 与 gold SQL 的执行结果是否等价。
- 分桶：按 easy / medium / hard / extra 难度统计。
- 评测脚本：
  - `python -m eval.fair_ab_eval`
  - `python -m eval.rag_ablation_eval`
  - `python -m eval.schema_style_eval`
- RAGAS：保留为辅助工具，但不作为本项目主指标。Text-to-SQL 的最终目标是 SQL 执行正确，而不是回答文本或检索上下文看起来相关。

## 公平 A/B：无 RAG vs 有 RAG

### concert_singer · 45 题

| 方案 | 准确率 |
| --- | ---: |
| noRAG once | 0.822 |
| noRAG retry | 0.800 |
| RAG once | 0.867 |
| RAG retry | 0.889 |

结论：RAG 有稳定增益，尤其在 medium 难度上更明显；retry 并不总是提升，无 RAG 下甚至略有下降。

### cre_Doc_Template_Mgt · 50 题

| 方案 | 准确率 |
| --- | ---: |
| noRAG once | 0.860 |
| noRAG retry | 0.880 |
| RAG once | 0.940 |
| RAG retry | 0.940 |

结论：RAG 明显优于无 RAG；retry 在该库中对 noRAG 有帮助，但对 RAG 没有额外收益。

### ALL · 100 题

| 方案 | 准确率 |
| --- | ---: |
| noRAG once | 0.740 |
| noRAG retry | 0.780 |
| RAG once | 0.760 |
| RAG retry | 0.760 |

结论：跨库小样本下，RAG 提升不如单库明显。说明通用 Text-to-SQL 不能只看单库效果，跨域评测更容易暴露检索噪声、few-shot 泛化和 schema linking 的边界。

## RAG 消融

### ALL · 100 题

| 方案 | 准确率 |
| --- | ---: |
| schema_only | 0.730 |
| schema_rerank | 0.740 |
| schema_fewshot | 0.790 |
| schema_fewshot_expand | 0.750 |
| full_rag | 0.750 |

结论：few-shot 是当前最稳定的收益来源；query expansion 和 full RAG 没有稳定超过 schema + few-shot。

### concert_singer · 45 题

| 方案 | 准确率 |
| --- | ---: |
| schema_only | 0.822 |
| schema_rerank | 0.822 |
| schema_fewshot | 0.889 |
| schema_fewshot_expand | 0.844 |
| full_rag | 0.867 |

结论：few-shot 明显提升；query expansion 在该库引入噪声。

### cre_Doc_Template_Mgt · 50 题

| 方案 | 准确率 |
| --- | ---: |
| schema_only | 0.880 |
| schema_rerank | 0.900 |
| schema_fewshot | 0.960 |
| schema_fewshot_expand | 0.960 |
| full_rag | 0.900 |

结论：few-shot 仍是核心收益；full RAG 反而低于 schema + few-shot，说明业务文档上下文需要按场景开启，不能默认堆上下文。

## Schema 描述增强实验

### concert_singer · 45 题

| 方案 | basic | enriched | diff |
| --- | ---: | ---: | ---: |
| schema_only | 0.822 | 0.800 | -0.022 |
| schema_rerank | 0.822 | 0.844 | +0.022 |
| schema_fewshot | 0.889 | 0.911 | +0.022 |
| schema_fewshot_expand | 0.889 | 0.889 | +0.000 |
| full_rag | 0.889 | 0.889 | +0.000 |

### cre_Doc_Template_Mgt · 50 题

| 方案 | basic | enriched | diff |
| --- | ---: | ---: | ---: |
| schema_only | 0.920 | 0.860 | -0.060 |
| schema_rerank | 0.900 | 0.800 | -0.100 |
| schema_fewshot | 0.960 | 0.920 | -0.040 |
| schema_fewshot_expand | 0.960 | 0.900 | -0.060 |
| full_rag | 0.940 | 0.900 | -0.040 |

结论：schema 描述增强不是天然增益。有的库会提升，有的库会下降。生产默认应保留 basic schema，enriched schema 必须经过离线 A/B 后再上线。

## 当前阶段总判断

| 问题 | 阶段结论 |
| --- | --- |
| RAG 是否有价值 | 有，但收益和库、问题分布、检索质量有关。 |
| 哪个模块最关键 | few-shot 目前最稳定；schema 是基础能力。 |
| rerank 是否必要 | 有时提升，有时不明显；更适合作为可配置项。 |
| query expansion 是否默认开启 | 不建议。当前实验中收益不稳定，可能引入噪声。 |
| full RAG 是否一定最好 | 不是。业务文档上下文在通用 benchmark 中可能拖累 SQL 生成。 |
| retry 是否一定提升 | 不是。retry 可能修正错误，也可能改坏正确 SQL。 |
| RAGAS 是否作为主指标 | 不建议。Text-to-SQL 应以执行准确率为主。 |

## 后续欢迎贡献的方向

- 更多数据库和更大样本的公平 A/B。
- 更细粒度的错误归因：schema linking 错误、join path 错误、聚合错误、条件遗漏等。
- few-shot 选择策略优化：同库优先、难度相近、结构相似、SQL 模板相似。
- schema enriched 内容的人工审核与自动质量评估。
- Prometheus 指标补充：429/503、inflight、LLM 排队时间、各 LangGraph 节点耗时。
- 多 worker / 多容器下的 Prometheus multiprocess 指标方案。
