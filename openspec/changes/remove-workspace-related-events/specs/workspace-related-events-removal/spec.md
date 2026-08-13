## Purpose

移除 Workspace 首页和摘要接口中与事务及业务详情重复的个人相关事件列表，同时保留权威事件记录和既有事件查看入口。

## ADDED Requirements

### Requirement: Workspace 不再展示相关事件摘要
系统 MUST 从 Workspace 首页删除“相关事件”模块，并停止执行仅供该模块使用的成员事件查询。

#### Scenario: 成员打开 Workspace 首页
- **WHEN** 完整 Workspace 成员打开首页
- **THEN** 页面不显示“相关事件”列表

### Requirement: Workspace Summary 不再返回最近事件
Workspace Summary API MUST 不再声明或返回 `recent_events`。

#### Scenario: 客户端读取 Workspace Summary
- **WHEN** 已授权客户端读取 Workspace Summary
- **THEN** 响应不存在 `recent_events`

### Requirement: 权威事件入口保持不变
系统 MUST 保留公开事件时间线、事件数据和业务详情中的既有事件记录能力。

#### Scenario: 删除 Workspace 摘要后查看事件
- **WHEN** 用户通过既有公开事件或业务详情入口查看事件
- **THEN** 该入口的事件数据与权限行为保持不变
