## Purpose

定义 Workspace 删除重复的“下一步动作”摘要后，首页、服务器端 context 和公开 Workspace Summary API 必须共同停止暴露该功能，同时保证其来源领域模块继续独立工作。

## ADDED Requirements

### Requirement: Workspace 不再展示下一步动作摘要
系统 MUST 从 Workspace 首页完整移除“下一步动作”模块，不得继续展示由任务、申诉或资源预警推导出的固定动作标签。

#### Scenario: 成员打开 Workspace 首页
- **WHEN** 已登录且有完整 Workspace 权限的成员打开首页
- **THEN** 页面不包含“下一步动作”模块或其摘要标签
- **THEN** “我的事务”、任务、申诉和资源预警等保留模块仍按各自规则展示

### Requirement: Workspace Summary API 不再返回下一步动作
成员 Workspace Summary API MUST 不再声明或返回 `next_actions` 字段。

#### Scenario: 客户端读取 Workspace Summary
- **WHEN** 已授权客户端请求成员 Workspace Summary
- **THEN** 响应中不存在 `next_actions`
- **THEN** 其他既有 Workspace Summary 字段保持原有语义

### Requirement: 删除摘要不得删除来源领域数据
系统 MUST 保留任务、申诉和资源预警的领域查询、页面模块及 API 字段，不得因删除派生摘要而删除其来源数据。

#### Scenario: 成员同时存在任务、申诉和资源预警
- **WHEN** Workspace 不再生成下一步动作摘要
- **THEN** 对应的任务、申诉和资源预警仍可从其既有页面区域和 Workspace Summary 字段中读取
