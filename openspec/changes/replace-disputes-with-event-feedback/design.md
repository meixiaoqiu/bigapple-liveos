## Context

当前 `Dispute` 可关联任务或积分流水，也可以完全不关联业务事实；`claimant_member`、`respondent_member` 与 `handler`/`reviewer` JSON 混合了主体、责任和展示信息。Workspace 首页直接创建申诉，Observer 与 Summary 又按旧模型显示状态。项目同时存在面向用户的 `Event` 和不可变审计链 `SystemEvent`：前者有可见性和详情页，后者用于证明事实完整性。

## Goals / Non-Goals

**Goals:** 用强制 `Event` 外键、明确成员外键和统一公开核实流程替换旧模型；使事件详情成为创建入口；由提交人控制自身身份展示范围；同步代码、迁移和公开契约，不留旧命名。

**Non-Goals:** 不统一或重写各领域的纠错动作；不允许反馈直接编辑原事件；不提供匿名提交；不把 `SystemEvent` 改造成第二种反馈目标。

## Decisions

### 1. `Event` 是唯一反馈目标

`EventFeedback.related_event` 使用 `ForeignKey(Event, PROTECT)` 且必填。选择 `Event` 是因为它具有稳定业务语义、可见性和用户详情页；`SystemEvent` 是审计证明，可从事件详情查看或作为证据引用。未采用 `content_type + object_id`，因为多态字符串会削弱数据库完整性并重新引入含糊语义。

### 2. 直接删除旧表并创建新表

新增迁移删除 `Event.related_dispute_id` 与 `Dispute`，再创建 `EventFeedback`，并为处理结果事件增加 `resolution_event` 外键。现有数据仅为开发、seed 和测试数据，不做迁移映射；未采用 `RenameModel`，因为旧字段和新语义并非一一对应。

### 3. 模型使用明确主体和责任外键

核心字段为：

- `feedback_id` 主键；
- `related_event` 必填；
- `feedback_type`；
- `status`；
- `submitted_by` 必填；
- `subject_member` 可空；
- `statement`、`requested_outcome`、`evidence_refs`；
- `submitter_visibility`，取 `public`、`parties_and_handlers` 或 `handlers_only`；
- `privacy_reason`，限制身份展示时必填；
- `assigned_handler`、`concluded_by` 可空；
- `response_statement`、`responded_by`、`responded_at`；
- `conclusion`、`conclusion_reason`、`resolution_event` 可空；
- `submitted_at`、`verification_started_at`、`concluded_at`、`closed_at`、`metadata`。

没有 `appeal_path`、`related_task`、`related_ledger_entry` 或 actor JSON；业务来源从 `related_event` 获取，审计行为人由 `SystemEvent.actor_member` 记录。

### 4. 默认实名公开，提交人控制自身身份展示

所有类型默认 `submitter_visibility=public`。提交人可选择只向相关方与处理人展示，或仅向处理人展示；非公开选择要求 `privacy_reason`。这不是匿名：数据库始终保存 `submitted_by`，处理人始终可见。公开 serializer 按范围隐藏提交人和理由，但反馈事实、回应与结论原则上公开。第三方隐私由独立脱敏规则处理，不能由提交人授权公开。

### 5. 处理权限沿用治理管理权限

第一版使用项目现有管理员能力判断作为核实和结案权限，不新增隐式角色。处理 service 接受明确 `Member`，并在 view/API 入口通过 `AuthorizationService` 现有治理权限检查；相关方只获得提交正式回应的权限。后续如拆分专门反馈职责，应通过 RolePermission 正式配置。

### 6. 反馈生命周期和事件命名整体替换

新服务模块 `core.event_feedback_services` 提供 `submit_event_feedback`、`start_event_feedback_verification`、`request_event_feedback_response`、`respond_to_event_feedback`、`conclude_event_feedback`、`close_event_feedback` 和 `withdraw_event_feedback`。统一账本事件对应改为 submitted、verification_started、response_requested、responded、concluded、closed、withdrawn，聚合类型为 `EventFeedback`。业务 `Event` 如需描述过程，使用 `event_feedback` 类型并通过新 `related_feedback_id` 字段关联。

### 7. 页面入口与事务投影分工

公开 Event 详情继续匿名可读；登录成员获得反馈表单。反馈详情默认公开反馈、回应、结论与依据，并按 `submitter_visibility` 隐藏身份；相关方和处理者获得相应动作。Workspace 仅投影反馈状态，不再保留表单或独立状态列表。Observer Dashboard 将“未关闭申诉”改为“核实中反馈”，且遵守身份与第三方字段脱敏。

### 8. 公开契约不保留兼容字段

删除 `dispute.schema.json`、example 和 OpenAPI `/disputes`，新增 `event-feedback` 契约。Event 的 `related_dispute_id` 改为 `related_feedback_id`；Workspace Summary 的 `open_disputes`、`dispute_history` 改为 `open_feedbacks`、`feedback_history`。契约先于实现修改。

### 9. 状态转换、后台与公开内容采用同一权威边界

所有既有反馈状态转换都在 service 事务内按主键 `select_for_update()` 重新读取，再判断状态并追加账本，调用方传入的实例不作为并发事实。Django Admin 仅用于查询反馈记录，不允许新增、编辑或删除权威字段。成员提交的原始陈述、期望结果、证据和回应始终只向提交人、明确相关方及处理人展示；公开页面只显示经处理人核实后形成的结论、依据和责任人。创建 API 严格拒绝未知字段、错误 JSON 容器类型和错误数组元素类型。Workspace 按当前状态和明确责任关系区分“需要我处理”与“等待他人”。

MySQL 专用并发测试必须列入 GitHub Actions 的 `mysql-concurrency` job，并使用 `live_os.settings_real`，不能只依赖默认 SQLite 完整回归中的条件跳过。

## Risks / Trade-offs

- [迁移删除开发数据] → 项目尚未上线且用户明确选择无历史包袱；迁移说明和测试明确不做数据转换。
- [事件可见性校验分散] → 提取复用现有 Observer 可见性规则的查询辅助函数，创建和读取使用同一判定。
- [身份展示范围实现错误] → 默认 public，三个范围使用统一 serializer 判定，并覆盖匿名访客、相关方、普通成员和处理者测试。
- [机械重命名遗漏] → 使用全仓搜索覆盖模型、FK、payload、seed、reset、Admin、API、Observer、Workspace、contracts 和 docs，最终断言产品代码不存在 `Dispute`/`dispute_*` 领域残留；兑换订单自身的 `dispute` 动词另行改为“问题反馈”但不与 EventFeedback 混为一表。
- [反馈结论被误当成领域纠错] → service 只记录结论与可选结果事件，不直接修改任务、积分、资源、财务或资格状态。

## Migration Plan

1. 先更新技术契约，删除旧 dispute 契约并新增 event-feedback 契约。
2. 新增模型与 destructive migration；修改 Event 和 SystemEvent 类型。
3. 实现反馈 service、serializer、Admin 和 API。
4. 将事件详情接入创建与查看，将 Workspace 事务投影切换并删除旧模块。
5. 更新 Observer Dashboard、seed、world reset、测试和文档。
6. 运行迁移漂移、契约、OpenSpec、定向和完整回归。

回滚需要恢复旧代码和旧 schema 后重建开发数据库；不承诺从新反馈表逆向恢复旧 Dispute 数据。
