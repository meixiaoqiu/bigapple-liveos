## Why

Workspace 首页“当前任务”和“可领取任务”仍承载任务操作，导致首页继续重复领域功能。将这些能力迁入独立任务中心和任务详情后，首页可以只承担事务聚合与导航职责。

## What Changes

- 新增任务中心，集中展示本人的当前任务、可领取任务和最近结束任务。
- 扩展任务详情：开放任务可查看并领取，本人进行中任务可提交劳动和证据，待验收及结束任务显示状态与结果。
- 将领取和提交后的返回入口改为相应任务详情。
- 删除 Workspace 首页“当前任务”“可领取任务”模块及页面专属查询，保留任务中心导航入口。
- **BREAKING**：从 Workspace Summary API、schema 和 example 删除 `available_tasks`、`active_tasks`。

### 目标

- 让任务发现、领取、执行和历史查看归属任务领域页面。
- 进一步收敛 Workspace 首页重复模块和无人使用的 API 字段。

### 非目标

- 不改变任务状态机、领域 service、积分或验收规则。
- 不删除 Task 数据或管理/验收后台入口。
- 不删除其他 Workspace 模块。

### 权限影响

完整 Workspace 成员可查看开放任务和自己的任务；他人非开放任务不可见。领取和劳动提交继续由既有 service 校验。

### 数据影响

无数据库 schema、迁移或权威数据变化。

### 公开契约影响

Workspace Summary API 删除 `available_tasks`、`active_tasks`，属于破坏性 payload 变更。

## Capabilities

### New Capabilities

- `workspace-task-center`: 定义任务中心、可操作任务详情与首页任务模块迁移后的行为。

### Modified Capabilities

无。

## Impact

- Workspace 路由、视图、模板、context、事务链接和测试。
- Workspace Summary API、技术契约及产品文档。
- 无新增依赖或迁移。
