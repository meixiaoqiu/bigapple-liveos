## Why

资源预警属于库存运营状态，普通成员无需在 Workspace 首页持续查看。当前首页重复查询和展示预警，而具备管理权限的成员已经通过 `/workspace/inventory/` 处理资源，因此应将预警完整收归资源页面。

## What Changes

- 将 `/workspace/inventory/` 的资源预警区设为页面首要内容，并确保预警查询不受全部资源列表上限影响。
- 从 Workspace 首页删除资源预警统计、资源预警模块及其专属查询。
- **BREAKING**：从 Workspace Summary API、schema 和 example 删除 `resource_warnings`。
- 同步 Workspace、资源页面和 API 文档以及迁移期模块清单。

### 目标

- 让库存管理人员进入资源页面后首先看到完整、有界且可处置的资源预警。
- 让 Workspace 首页只保留与普通成员相关的个人状态和事务。

### 非目标

- 不改变资源预警判定条件、库存调整 service 或资源权限。
- 不向普通成员开放 `/workspace/inventory/`。
- 不删除 Observer 中面向公开观察的资源状态。

### 权限影响

资源预警的内部处置视图继续仅对具备现有库存管理入口权限的管理员开放；普通成员不再从 Workspace 首页或 Summary API 获得该列表。

### 数据影响

无模型、迁移或权威数据变化。

### 公开契约影响

Workspace Summary 删除 `resource_warnings`，属于破坏性 payload 变更。

## Capabilities

### New Capabilities

- `inventory-resource-warnings`: 定义资源页面中的首要预警展示以及 Workspace 首页和 Summary 移除预警后的边界。

### Modified Capabilities

无。

## Impact

- Workspace 首页模板、context、Summary API 与测试。
- 资源列表查询、模板与测试。
- sibling docs 技术契约和产品/API 文档。
