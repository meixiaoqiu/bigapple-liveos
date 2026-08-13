## Context

Workspace 当前读取最近 50 条全局 `Event`，再按当前成员过滤并最多展示 10 条；相同业务变化已由“我的事务”、业务详情或公开时间线承载。Summary API 复用首页 context 输出该列表。

## Goals / Non-Goals

**Goals:** 删除重复页面投影和 API 字段，并同步机器契约。

**Non-Goals:** 不修改事件模型、事件写入、公开时间线或详情页事件能力。

## Decisions

### 1. 完整删除专属查询

删除 `workspace_context` 中的 Python 扫描，而不是保留不可见 context 数据，因为该数据已无消费者且查询存在漏项语义。

### 2. Summary 字段直接删除

先修改技术契约，再删除 payload 字段，不保留空数组或兼容别名，以免继续表达已取消的产品能力。

## Risks / Trade-offs

- [误删权威事件能力] → 修改范围限定 Workspace context、首页模板和 Summary 序列化，不触碰 Observer、Event 模型或业务详情。
- [active OpenSpec 语义冲突] → 同步聚合首页的保留模块清单，使后续确认覆盖初次保留基线。

## Migration Plan

先修改契约，再删除实现与页面模块，最后同步测试和文档。无数据迁移；回滚需整体恢复契约和摘要字段。
