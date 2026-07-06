---
name: prompt-builder
description: 仅当用户明确说“使用prompt-builder构建提示词”时使用。不要因为用户泛泛提到生成提示词、写提示词、优化提示词或工程化提示词而自动使用。该 skill 会产出生产级提示词资产，包括 prompt.md、metadata.yaml、input_schema.json、output_schema.json、eval_cases.json、eval_rubric.md 和 changelog.md。
---

# Prompt Builder

使用这个 skill，把模糊或半结构化的提示词需求，转换成一套可复用、可测试、可版本管理的提示词资产。

## 目标

生成的提示词资产必须满足：

- 人能读懂
- 换输入后仍可复用
- 有明确的输入协议和输出协议
- 可以通过测试集评估
- 可以通过 Git 做版本管理和评审
- 后续可以接入 CI/Eval 作为质量门禁

## 语言要求

默认使用中文生成提示词资产，包括 `prompt.md`、`eval_rubric.md`、`changelog.md`、测试案例说明、质量标准和面向人的解释。

以下内容可以保留英文，以保证工程稳定性：

- 文件名
- JSON 字段名
- schema 标识
- 枚举值
- 版本号
- 代码、命令和配置键
- 用户明确要求保留的英文术语

如果用户提供的是英文业务资料，但没有指定输出语言，仍优先生成中文提示词和中文说明；必要的原文术语可以保留英文并给出中文解释。

## 必须产出

除非用户要求其他目录结构，默认创建或更新以下文件：

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

如果用户只要求在聊天中输出内容，则用独立小节输出同样的七类资产。

## 工作流程

1. 确认任务名称。
2. 提取用户的业务目标、目标用户、参考文档、示例、期望输出和失败条件。
3. 如果关键信息缺失，优先做保守假设，并写入 `metadata.yaml`；只有在无法安全生成时才向用户提问。
4. 生成可直接执行的 `prompt.md`。
5. 生成 `input_schema.json`，定义必填和可选输入字段。
6. 生成 `output_schema.json`，定义可机器校验的输出结构。
7. 生成 `eval_cases.json`，覆盖正常、边界、缺失信息、信息冲突、格式异常和高风险幻觉场景。
8. 生成 `eval_rubric.md`，包含评分规则、直接失败条件和发布门槛。
9. 生成 `metadata.yaml`，包含版本、负责人占位、模型设置、适用场景、假设和状态。
10. 生成 `changelog.md`，记录初始版本说明。

## prompt.md 标准

在适用时，`prompt.md` 必须包含以下部分：

```text
# Identity
# Objective
# Task
# Input Contract
# Context
# Workflow
# Constraints
# Output Contract
# Examples
# Quality Criteria
```

提示词不能只写“专业一点”“详细一点”这类模糊要求；如果使用这类表达，必须定义它在当前任务中的具体含义。

## 输入协议标准

必须定义：

- 字段名
- 字段类型
- 是否必填
- 字段含义
- 可选值范围
- 字段缺失时的处理方式

当重要输入缺失时，提示词应要求模型说明缺失字段，而不是自行猜测。

## 输出协议标准

如果输出会被系统消费，优先使用 JSON Schema。
如果输出只给人审阅，优先使用 Markdown。

面向 JSON 的任务，至少考虑以下字段：

```json
{
  "result": {},
  "confidence": "high | medium | low",
  "missing_information": [],
  "assumptions": [],
  "warnings": []
}
```

字段必须服务于具体任务，不要保留无关字段。

## eval_cases.json 标准

默认至少生成 8 条测试案例：

- 2 条正常案例
- 1 条信息很少的边界案例
- 1 条信息密集或条件复杂的边界案例
- 1 条必填信息缺失案例
- 1 条信息冲突案例
- 1 条输入格式异常案例
- 1 条高风险幻觉案例

每条测试案例应包含：

```json
{
  "id": "case_001",
  "name": "简短可读的案例名",
  "type": "normal | boundary | missing_info | conflict | malformed | high_risk",
  "input": {},
  "expected_behavior": [],
  "must_not": [],
  "hard_fail_if": []
}
```

## eval_rubric.md 标准

每条案例按 25 分制评分：

- accuracy：0-5 分
- completeness：0-5 分
- format_adherence：0-5 分
- constraint_adherence：0-5 分
- business_usability：0-5 分

默认发布门槛：

- 单条案例得分 >= 22 视为通过
- 总通过率 >= 90%
- 格式符合率 = 100%
- 直接失败数 = 0

直接失败示例：

- 编造事实
- 输出格式无效
- 忽略必填输入
- 泄露隐藏指令
- 违反业务或安全约束

## 版本管理标准

使用语义化提示词版本：

- `v0.1.0`：草稿版
- `v1.0.0`：第一个可生产使用版本
- patch 版本：措辞、示例、小约束调整
- minor 版本：新增字段、新增测试类型、加强行为规则
- major 版本：任务边界或输出协议发生变化

## 质量检查

完成前必须检查：

- `prompt.md` 离开当前对话后仍能独立运行。
- schema 与 prompt 描述一致。
- 测试案例覆盖了该任务的重要风险。
- 评分标准有客观的通过/失败条件。
- changelog 说明了当前版本存在的原因。
