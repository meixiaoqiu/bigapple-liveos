## Context

参见 `proposal.md`。当前同一组 `available_tasks`、`active_tasks`、`open_disputes` 和 `resource_warnings` 数据既供领域模块使用，也被额外转换为 `next_actions`。转换结果同时进入 HTML context 与 Workspace Summary API，API 字段已由 sibling docs 仓库中的 JSON Schema 声明为必填。

## Goals / Non-Goals

**Goals:**

- 完整删除派生摘要的页面、组装逻辑和公开字段。
- 保留来源数据及其领域模块，避免把共享查询误判为摘要专属代码。
- 使技术契约、实现、测试和产品文档保持一致。

**Non-Goals:**

- 不调整“我的事务”或待处理事项聚合。
- 不改变任务、申诉和资源预警的筛选、权限或排序。
- 不提供旧字段兼容期或空数组占位。

## Decisions

### 1. 直接删除 API 字段，不保留弃用占位

技术契约先移除 `next_actions` 的 required 声明与 property，随后实现停止返回该键。未采用返回空数组的兼容方案，因为它仍然保留无产品职责的契约和服务器端概念，违背完整删除目标。

### 2. 只删除派生层，不删除共享来源查询

删除动作标签映射、派生函数和两个 context 键；任务、申诉、资源预警查询继续存在，因为其他首页模块和 API 字段仍直接消费它们。未采用连带删除查询的方案，因为会破坏明确要求保留的领域功能。

### 3. 通过否定断言保护删除结果

页面测试断言模块标题不存在，API 测试断言响应键不存在，并继续断言来源领域数据存在。这样能同时防止模块被误加回和共享功能被误删。

## Risks / Trade-offs

- [外部客户端仍读取 `next_actions`] → 这是用户明确授权的破坏性契约变更；同步 schema、example 和产品文档，验证仓库内无其他消费者。
- [删除共享数据查询造成其他模块回归] → 仅删除派生层，并运行 Workspace 与 API 回归。
- [旧文档继续宣称模块存在] → 搜索 docs 中所有相关引用并同步更新。

## Migration Plan

1. 先修改技术契约 schema 和 example。
2. 删除 HTML、context 派生逻辑和 API 字段。
3. 更新测试与产品文档，运行契约、Workspace 和 API 验证。
4. 若需回滚，整体恢复契约字段、派生逻辑和页面模块；无数据迁移。
