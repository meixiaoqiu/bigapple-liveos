## Context

参见 `proposal.md`。资源页面已经在标题下方展示低库存预警，但当前预警是从最多 50 条全部资源的内存列表中派生，可能漏掉列表上限之外的预警；首页则独立查询并展示全部预警，Summary API 继续序列化相同列表。

## Goals / Non-Goals

**Goals:** 让资源页面成为内部预警的唯一处置入口，预警置于全部资源列表之前且查询语义正确，同时删除首页和 Summary 的重复输出。

**Non-Goals:** 不改变 `current_stock <= warning_threshold` 判定、不调整库存权限、不改变公开 Observer。

## Decisions

### 1. 预警与全部资源使用独立数据库查询

预警查询直接使用数据库条件和稳定排序，不从受 `_RESOURCE_LIST_LIMIT` 限制的资源列表派生。相比提高列表上限，这能保证预警正确性又不扩大常规列表成本。

### 2. 无预警时仍保留首要状态区

资源页面在标题之后、全部资源之前始终渲染预警区域；无预警时显示明确成功状态。相比完全隐藏区域，这能让管理人员确认系统已检查而不是页面遗漏。

### 3. 删除 Summary 字段而非保留空数组

先修改 sibling docs 技术契约，再删除实现字段和首页 context 查询。仓库内消费者同步改为断言字段不存在，避免继续维持无人使用的兼容负担。

## Risks / Trade-offs

- [预警数量无限增长导致页面过重] → 资源主档本身是受控运营数据，预警必须完整呈现；全部资源表仍保持既有 50 条上限。
- [误删 Observer 公开资源状态] → 修改范围限定 Workspace context、Summary 与内部 inventory 模板，不触碰 Observer 查询。
- [迁移期规格再次冲突] → 同步 `aggregate-workspace-home` 的保留模块清单和初始存在性基线。

## Migration Plan

先更新 Summary 契约，再独立实现资源预警查询和首要空状态；随后删除 Workspace 首页展示、context 与 API 字段，最后同步测试和文档。无数据迁移；回滚需整体恢复契约、API 字段和首页模块。
