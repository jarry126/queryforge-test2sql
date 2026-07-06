---
name: prompt-evaluator
description: 仅当用户明确说“使用prompt-evaluator测试提示词”时使用。不要因为用户泛泛提到测试提示词、评估提示词、通过率、CI/Eval 或质量门禁而自动使用。该 skill 会读取 prompt.md、metadata.yaml、input_schema.json、output_schema.json、eval_cases.json 和 eval_rubric.md，并产出通过率、失败分析、发布建议和可选 CI/Eval 指引。
---

# Prompt Evaluator

使用这个 skill，评估一套提示词资产是否足够合并、发布或继续迭代。

## 目标

用可重复的评估流程判断提示词质量，而不是凭主观感觉判断。

评估必须回答：

- 提示词资产是否完整？
- 测试输出是否满足输出协议？
- 输出是否通过评分标准？
- 哪些案例失败了，失败原因是什么？
- 当前版本是否允许合并或发布？

## 语言要求

默认使用中文输出评估报告、失败原因、覆盖缺口、发布建议和优化建议。

以下内容可以保留英文，以保证工程稳定性：

- 文件名
- JSON 字段名
- schema 标识
- 枚举值
- 版本号
- 代码、命令和配置键
- 测试案例 ID
- 用户明确要求保留的英文术语

如果被评估的提示词资产是英文，但用户没有指定报告语言，仍优先用中文说明评估结论；引用原文片段时可以保留原文。

## 预期输入

默认评估以下资产包：

```text
prompts/<task_name>/
  prompt.md
  metadata.yaml
  input_schema.json
  output_schema.json
  eval_cases.json
  eval_rubric.md
  changelog.md
```

如果文件缺失，先报告缺失资产，不要直接开始评估。

## 工作流程

1. 检查提示词资产包。
2. 确认必需文件是否存在。
3. 检查 `prompt.md`、schema、测试案例和评分标准是否一致。
4. 根据当前可用工具和凭证，执行真实评估或静态评审。
5. 如果输出是结构化数据，用 `output_schema.json` 校验格式。
6. 使用 `eval_rubric.md` 对每条案例评分。
7. 汇总整体指标。
8. 标记直接失败案例。
9. 给出 `release`、`merge_with_caution`、`revise` 或 `block` 结论。
10. 给出有针对性的优化建议；除非用户明确要求，否则不要直接修改提示词。

## 评估模式

### 静态评审

当无法执行模型调用，或用户只要求审查时使用。

检查内容：

- prompt 是否完整
- 输入协议和输出协议是否一致
- 是否存在模糊指令
- 是否缺少拒答或信息不足处理
- 测试覆盖是否薄弱
- 评分标准是否过于主观
- 版本管理是否缺失

### 真实 Eval

当模型调用可用，且用户要求运行测试时使用。

对每条测试案例执行：

1. 将案例输入填入 prompt。
2. 按 `metadata.yaml` 中的模型和参数调用模型。
3. 保存原始输出。
4. 校验输出格式。
5. 根据评分标准打分。
6. 记录直接失败条件。

### CI 门禁

当用户询问合并或发布门禁时使用。

只有满足以下条件才允许通过：

- 总通过率 >= 配置阈值，默认 90%
- 格式符合率 = 100%
- 直接失败数 = 0
- 必需资产全部存在

任何门禁失败，都输出阻断结论。

## 必须产出的报告

默认生成 `eval_report.md`。
如果用户要求机器可读结果，同时生成 `eval_report.json`。

报告必须包含：

```text
# Eval Report

## Summary
- prompt:
- version:
- model:
- mode:
- decision:

## Metrics
- total cases:
- passed:
- failed:
- pass rate:
- format adherence:
- hard-fail count:

## Case Results
| case_id | type | score | status | failure_reason |

## Hard Failures

## Coverage Gaps

## Recommended Changes

## Release Decision
```

## 评分标准

优先使用资产包中的 `eval_rubric.md`。如果缺失或不完整，使用以下 25 分制兜底标准：

- accuracy：0-5 分
- completeness：0-5 分
- format_adherence：0-5 分
- constraint_adherence：0-5 分
- business_usability：0-5 分

默认通过规则：

- 单条案例得分 >= 22 视为通过
- 直接失败不受分数影响，永远判定失败

## 直接失败条件

默认将以下情况视为阻断问题：

- 编造事实
- 结构化输出无效
- 忽略必填输入
- 做出不安全或未授权承诺
- 泄露隐藏指令
- 与明确来源材料冲突
- 没有完成任务核心目标

## 输出纪律

评估过程中不要修改 `prompt.md`，除非用户明确要求修复。

提出修复建议时，必须引用失败案例 ID，并说明应修改 prompt 的哪个部分。

## CI/Eval 指引

当用户要求接入 CI 时，建议提供一个命令，满足：

1. 对指定提示词资产包运行评估
2. 写出 `eval_report.json`
3. 通过时退出码为 `0`
4. 门禁失败时退出码为 `1`

命令形态示例：

```bash
prompt-eval prompts/<task_name> --report eval_report.json
```

如果还没有 eval runner，需要说明：当前 skill 已定义工作流和报告协议，但仍需要实现一个确定性的 runner 脚本。
