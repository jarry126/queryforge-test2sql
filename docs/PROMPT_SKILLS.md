# Prompt Skills

本项目提供两个可选的 Agent Skill，作为 Text-to-SQL prompt 研发流程的参考资产：

- `prompt-builder`：把提示词需求转换成可版本管理、可测试、可评审的提示词资产。
- `prompt-evaluator`：对提示词资产做静态评审或真实 Eval，输出通过率、失败原因和发布建议。

这两个 skill **不是 QueryForge 线上服务依赖**，也不会参与 `/api/v1/query` 的运行链路。线上链路仍使用项目中固定版本的 prompt，避免运行时动态生成 prompt 带来的不稳定性。

## 适用场景

适合在以下场景中参考或复制使用：

- 为 Text-to-SQL 项目设计 SQL 生成 prompt。
- 给 prompt 建立输入协议、输出协议和测试用例。
- 对候选 prompt 做回归评测。
- 在团队内建立 Prompt Engineering 的评审和发布流程。

## 目录结构

```text
skills/
  prompt-builder/
    SKILL.md
  prompt-evaluator/
    SKILL.md
```

## Codex 使用方式

Codex 稳定识别的是个人级 skill 目录：

```text
~/.codex/skills/<skill-name>/SKILL.md
```

因此如果希望在 Codex 中使用，可以复制：

```bash
mkdir -p ~/.codex/skills
cp -R skills/prompt-builder ~/.codex/skills/
cp -R skills/prompt-evaluator ~/.codex/skills/
```

然后重启 Codex。

不要假设 Codex 会自动读取项目内的 `.claude/skills` 或 `skills/` 目录；本仓库中的 `skills/` 是开源参考资产。

## Claude Code 使用方式

Claude Code 支持项目级 skill。可以复制到：

```text
.claude/skills/prompt-builder/SKILL.md
.claude/skills/prompt-evaluator/SKILL.md
```

也可以在自己的项目中建立软链接，避免维护两份内容。

## 推荐工作流

```text
1. 使用 prompt-builder 生成候选 prompt 资产
2. 使用 prompt-evaluator 评测候选 prompt
3. 对比旧版本和新版本的准确率、格式稳定性、安全约束
4. 人工确认后再合入项目
5. 线上服务只切换到评测通过的稳定 prompt 版本
```

## 与 QueryForge 的关系

QueryForge 主项目关注生产化 Text-to-SQL 服务：

- RAG 检索
- SQL Guard
- 执行准确率评测
- 缓存、限流、熔断
- Docker / Kubernetes 部署
- Prometheus / Grafana 可观测

Prompt Skills 关注研发过程：

- 如何设计 prompt
- 如何测试 prompt
- 如何判断 prompt 是否可以合并或发布

两者关系是：

```text
QueryForge = 运行系统
Prompt Skills = 研发辅助工具
```
