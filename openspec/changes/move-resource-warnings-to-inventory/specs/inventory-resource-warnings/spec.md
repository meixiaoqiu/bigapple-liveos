## Purpose

将内部资源预警集中到具备处置权限的资源库存页面，并从普通成员 Workspace 与其摘要接口移除重复信息。

## ADDED Requirements

### Requirement: 资源页面首先展示完整预警
系统 SHALL 在 `/workspace/inventory/` 的全部资源列表之前展示当前低于或等于预警线的资源，并提供进入既有库存调整入口的动作；预警集合 MUST 不因全部资源列表的展示上限而漏项。

#### Scenario: 管理员打开存在预警的资源页面
- **WHEN** 具备现有资源页面访问权限的成员打开 `/workspace/inventory/`
- **THEN** 系统在全部资源之前展示所有当前预警资源及其库存、预警线和调整入口

#### Scenario: 资源页面不存在预警
- **WHEN** 当前没有资源低于或等于预警线
- **THEN** 系统在页面首要区域明确显示当前没有资源预警

### Requirement: Workspace 不再展示资源预警
系统 MUST 从 Workspace 首页删除资源预警统计和资源预警模块，并停止执行仅供这些首页展示使用的查询。

#### Scenario: 普通成员打开 Workspace 首页
- **WHEN** 完整 Workspace 成员打开首页
- **THEN** 页面不显示资源预警数量或资源预警列表

### Requirement: Workspace Summary 不再返回资源预警
Workspace Summary API MUST 不再声明或返回 `resource_warnings`。

#### Scenario: 客户端读取 Workspace Summary
- **WHEN** 已授权客户端读取 Workspace Summary
- **THEN** 响应不存在 `resource_warnings`
