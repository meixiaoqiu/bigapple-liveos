## Why

项目文档与 OpenSpec 规划产物同时出现中文和普通英文说明，增加了阅读、审核与长期维护成本，也会让新的 AI 会话继续生成不一致的文档语言。需要把中文设为项目级长期规范，而不是依赖每次对话临时提醒。

## What Changes

- 所有项目文档和 OpenSpec 规划产物的标题、正文、表格说明、需求名称、场景名称和任务说明默认使用中文。
- 代码、命令、文件路径、API、schema、payload、变量名、类名、函数名、协议名、产品名、OpenSpec 结构关键字及无法准确翻译的专业术语允许保留原文。
- 增加可重复的文档语言检查，报告不符合规范的普通英文标题、段落和任务说明。
- 将相同约束写入 `openspec/config.yaml`，使后续 OpenSpec 产物在生成阶段就遵守中文规范。
- 本变更不要求翻译代码标识、公开契约字段、第三方产品名或会因翻译而改变语义的技术内容。

## Capabilities

### New Capabilities

- `project-documentation-language`: 定义项目文档与 OpenSpec 产物的默认语言、允许保留原文的例外和自动检查行为。

### Modified Capabilities

无；当前尚无对应主规格。

## Impact

- 影响 `openspec/config.yaml`、OpenSpec 主规格与变更产物，以及 sibling 文档仓库中的 Markdown 文档规范。
- 可能增加只读项目检查，但不改变运行时代码、数据库、权限、API、schema、payload 或 technical contract。
- 不新增第三方依赖，不改变任何业务授权或数据状态。
