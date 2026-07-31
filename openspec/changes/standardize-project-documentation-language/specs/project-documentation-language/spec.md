## Purpose

统一 Big Apple 项目文档与 OpenSpec 规划产物的说明语言，使人类和 AI 在不同会话、仓库与变更中都能获得一致、可审核且易于长期维护的中文上下文。

## ADDED Requirements

### Requirement: 项目文档默认使用中文
系统与开发流程 MUST 要求所有受项目维护的文档使用中文编写标题、正文、表格说明、列表说明、需求名称、场景名称、任务说明、风险说明和迁移说明。

#### Scenario: 生成新的 OpenSpec 产物
- **WHEN** AI 或维护者创建 proposal、spec、design 或 tasks
- **THEN** 除允许保留原文的内容外，所有说明性文字均使用中文

#### Scenario: 创建或修改项目文档
- **WHEN** 维护者在 Live OS 仓库或 sibling 文档仓库中创建或修改 Markdown 文档
- **THEN** 新增或修改的说明性内容使用中文

### Requirement: 技术语义原文可以保留
代码、命令、文件路径、URL、API、schema、payload、数据库字段、变量名、类名、函数名、协议名、产品名、OpenSpec 结构关键字，以及无法准确翻译或翻译后会改变语义的专业术语 MAY 保留原文。该例外 MUST NOT 被用于保留普通英文标题、英文段落或英文任务说明。

#### Scenario: 文档包含代码标识
- **WHEN** 中文说明需要引用 `AuthorizationService`、`RoleAssignment`、`openspec validate` 或文件路径
- **THEN** 相应代码标识、命令和路径保留原文，周围说明仍使用中文

#### Scenario: 保留 OpenSpec 结构关键字
- **WHEN** 规格使用 `Purpose`、`Requirement`、`Scenario`、`MUST`、`SHALL`、`WHEN` 或 `THEN` 等结构与规范关键字
- **THEN** 这些关键字可以保留原文，需求名称、场景名称和行为说明仍使用中文

#### Scenario: 普通英文段落不属于例外
- **WHEN** 文档包含可以自然使用中文表达的完整英文标题、英文段落或英文任务说明
- **THEN** 文档不符合规范，即使其中夹杂少量技术术语

### Requirement: OpenSpec 生成阶段必须注入中文规则
OpenSpec 项目配置 MUST 向 proposal、spec、design、tasks、apply 和 archive 流程提供中文文档上下文与对应产物规则，使新的 AI 会话无需用户重复提醒即可遵守本规范。

#### Scenario: 新会话生成变更
- **WHEN** 新的 AI 会话读取项目 OpenSpec 配置并创建变更产物
- **THEN** 生成指令包含中文文档约束，产物默认使用中文

### Requirement: 文档语言必须可自动检查
项目 SHALL 提供可重复的只读检查，识别文档中的普通英文标题、英文段落和英文任务说明，并允许对代码块、命令、路径、结构关键字和经过审核的专业术语应用明确例外。

#### Scenario: 检查发现普通英文说明
- **WHEN** 受检查文档包含不在例外范围内的普通英文说明
- **THEN** 检查失败并报告文件、位置和触发内容

#### Scenario: 检查合法技术原文
- **WHEN** 文档只在代码、命令、路径、结构关键字或审核过的专业术语中使用原文
- **THEN** 检查通过且不会要求翻译会改变语义的内容

#### Scenario: 检查结果可复现
- **WHEN** 对相同文件状态重复执行语言检查
- **THEN** 检查产生相同结果，不依赖外部 AI 判断或网络服务
