## Why

首页“个人任务历史”与“我的事务”的最近结束任务重复，但目前仍被用作结果详情落点。应先提供真正的任务详情，再删除重复首页模块及无人消费的 API 字段。

## What Changes

- 新增成员本人可访问的只读任务详情页，展示任务结果、时间、劳动说明、证据和验收原因。
- 将“最近结束”任务的“查看结果”链接改为任务详情页。
- 删除首页“个人任务历史”模块及其独立服务器端查询。
- **BREAKING**：从 Workspace Summary API、schema 和 example 删除 `task_history`。
- 保留全部 Task 权威数据、事件和其他任务模块。

### 目标

- 以任务详情替代首页重复历史表格。
- 清除没有消费者的 API 字段与查询。

### 非目标

- 不删除任务历史数据，不改变任务状态机或写入服务。
- 不允许成员查看他人任务详情。
- 不删除其他 Workspace 模块。

### 权限影响

详情页仅允许任务的 `assignee_member` 本人访问；无新权限或授权例外。

### 数据影响

无 schema、迁移或权威数据写入变化。

### 公开契约影响

Workspace Summary API 删除必填字段 `task_history`，属于破坏性 payload 变更。

## Capabilities

### New Capabilities

- `workspace-task-detail`: 定义成员任务详情入口及替代首页任务历史后的行为边界。

### Modified Capabilities

无。

## Impact

- Workspace 路由、视图、模板、事务投影和测试。
- Workspace Summary API、技术契约及产品文档。
- 无新增依赖或迁移。
