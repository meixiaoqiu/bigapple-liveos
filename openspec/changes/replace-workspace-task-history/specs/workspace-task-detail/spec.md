## Purpose

为成员提供自己任务的稳定只读详情入口，以承接最近结束任务的结果追溯，并允许删除首页重复历史表格和无人使用的 Workspace Summary 历史字段。

## ADDED Requirements

### Requirement: 成员可以查看自己的任务详情
系统 SHALL 允许完整 Workspace 成员查看分派给自己的任务详情，包括状态、关键时间、劳动说明、证据和验收说明。

#### Scenario: 成员打开自己的已结束任务
- **WHEN** 当前成员访问分派给自己的任务详情
- **THEN** 系统展示任务身份、结果和已有的提交及验收信息

#### Scenario: 成员访问他人的任务
- **WHEN** 当前成员访问未分派给自己的任务详情
- **THEN** 系统拒绝访问且不泄露任务内容

### Requirement: 最近结束任务链接到详情
“我的事务”中的已结束任务 MUST 将查看结果动作链接到对应任务详情，不得依赖首页历史锚点。

#### Scenario: 从最近结束查看任务结果
- **WHEN** 成员点击已结束任务的查看结果动作
- **THEN** 系统打开该任务详情页

### Requirement: 首页与 API 删除任务历史集合
系统 MUST 删除首页“个人任务历史”模块，并且 Workspace Summary API MUST 不再声明或返回 `task_history`。

#### Scenario: 成员打开首页并读取 Summary API
- **WHEN** 成员打开 Workspace 首页或已授权客户端读取 Workspace Summary
- **THEN** 首页不包含“个人任务历史”模块且 API 响应不包含 `task_history`
- **THEN** Task 权威记录与其他任务模块继续保留
