## Purpose

将任务发现、领取、执行和结果查看集中到独立任务中心与任务详情，使 Workspace 首页不再承载重复任务列表，同时保持既有任务领域规则和权限不变。

## ADDED Requirements

### Requirement: 成员通过任务中心管理个人任务
系统 SHALL 为完整 Workspace 成员提供任务中心，分开展示本人的当前任务、可领取的开放任务和最近结束任务，并链接到任务详情。

#### Scenario: 成员打开任务中心
- **WHEN** 完整 Workspace 成员打开任务中心
- **THEN** 系统按当前、可领取和最近结束三个分组展示其可见任务

### Requirement: 任务详情按状态提供既有动作
系统 MUST 在开放任务详情提供领取动作，在本人已领取或进行中任务详情提供劳动说明和证据提交动作；所有动作 MUST 继续使用既有领域 service 和状态约束。

#### Scenario: 成员领取开放任务
- **WHEN** 成员从开放任务详情提交领取
- **THEN** 既有领取服务处理动作并返回该任务详情

#### Scenario: 成员提交自己的进行中任务
- **WHEN** 成员从自己任务详情提交劳动说明和证据
- **THEN** 既有劳动提交服务处理动作并返回该任务详情

#### Scenario: 成员访问他人非开放任务
- **WHEN** 成员访问未分派给自己且不开放的任务
- **THEN** 系统返回 404 且不泄露任务内容

### Requirement: Workspace 首页不再承载任务列表
系统 MUST 删除首页“当前任务”和“可领取任务”模块及其专属查询，并提供任务中心导航入口。

#### Scenario: 成员打开 Workspace 首页
- **WHEN** 成员打开 Workspace 首页
- **THEN** 页面不展示当前任务或可领取任务列表
- **THEN** 页面提供进入任务中心的入口，且“我的事务”任务链接进入对应详情

### Requirement: Workspace Summary 不再返回任务列表
Workspace Summary API MUST 不再声明或返回 `available_tasks` 和 `active_tasks`。

#### Scenario: 客户端读取 Workspace Summary
- **WHEN** 已授权客户端读取 Workspace Summary
- **THEN** 响应不存在 `available_tasks` 和 `active_tasks`
