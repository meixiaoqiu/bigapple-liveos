## Context

当前首页独立查询最近 10 条结束任务并渲染历史表格；“我的事务”另行查询最多 5 条结束任务，但查看结果链接回该表格。Workspace Summary API 同时返回 `task_history`，仓库内没有页面之外的实际消费者。

## Goals / Non-Goals

**Goals:** 以自有任务详情页取代首页表格，删除重复查询与 API 字段。

**Non-Goals:** 不建立通用审计引擎，不改变任务状态或授权规则。

## Decisions

### 1. 详情页采用成员本人所有权检查

视图从当前会话取得成员，并以 `task_id` 与 `assignee_member` 联合筛选。未采用仅凭完整 Workspace 权限查看任意任务的方案，避免扩大任务劳动记录可见范围。

### 2. 详情直接读取 Task 现有字段

页面展示模型字段及既有 metadata 中的劳动说明、证据和验收原因，不新增投影模型或持久化字段。

### 3. 契约字段直接删除

先从 sibling docs 的 schema 与 example 删除 `task_history`，再删除 API payload 和 context 查询，不保留空数组兼容。

## Risks / Trade-offs

- [详情泄露他人劳动记录] → 通过 assignee 联合筛选并增加越权测试。
- [最近结束链接失效] → 使用命名路由生成详情 URL 并增加页面测试。
- [外部消费者依赖字段] → 用户已确认无消费者；同步契约并执行全仓搜索。

## Migration Plan

先更新契约，再增加详情入口和改链，随后删除历史模块、查询及字段。回滚时整体恢复字段与首页模块，无数据迁移。
