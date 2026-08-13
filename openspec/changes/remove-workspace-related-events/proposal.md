## Why

Workspace 首页“相关事件”与“我的事务”及业务详情时间线重复，不提供独立操作价值。删除该摘要可减少首页噪声和一次不可靠的全局事件扫描。

## What Changes

- 删除 Workspace 首页“相关事件”模块及专属查询。
- **BREAKING**：从 Workspace Summary API、schema 和 example 删除 `recent_events`。
- 同步测试、产品文档和迁移期模块清单。
- 保留公开事件时间线、事件数据以及各业务详情中的事件记录。

### 目标

- 消除 Workspace 首页与事务/详情之间的重复事件摘要。
- 停止维护无人需要的 Summary 事件列表字段。

### 非目标

- 不删除或修改 `Event`、`SystemEvent` 数据。
- 不改变公开事件页面、事件权限或业务详情时间线。

### 权限影响

无授权规则变化；仅移除 Workspace 首页和 Summary 的重复读视图。

### 数据影响

无数据库 schema、迁移或权威数据变化。

### 公开契约影响

Workspace Summary 删除 `recent_events`，属于破坏性 payload 变更。

## Capabilities

### New Capabilities

- `workspace-related-events-removal`: 定义首页和 Summary 删除相关事件摘要，同时保留权威事件入口的边界。

### Modified Capabilities

无。

## Impact

- Workspace 模板、context、Summary API 与测试。
- sibling docs 技术契约和产品/API 文档。
