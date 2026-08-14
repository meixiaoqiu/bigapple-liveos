## Why

现有 `Dispute` 把任务申诉、成员冲突和各种争议混在一个以“申诉”为中心的模型中，且允许脱离事件创建，无法准确表达纠错、意见、投诉、举报、复核和风险。项目尚未上线，应直接建立以可见业务事件为核心的清晰模型，避免保留错误命名和兼容包袱。

## What Changes

- **BREAKING**：删除 `Dispute` 模型、`core_dispute` 表、旧申诉 service、Admin、seed、API、serializer、schema、example 和命名兼容层。
- 新增 `EventFeedback` 模型，每条反馈必须关联一个面向用户的 `Event`，类型为纠错、意见、投诉、举报、复核或风险。
- 六种反馈共用实名提交、公开记录、事实核实、相关方回应、公布结论和结束流程；类型只决定核实标准与后续领域动作。
- 反馈默认公开提交人身份；提交人可选择仅向相关方和处理人展示，或仅向处理人展示自己的身份，并必须说明限制展示理由。系统内部始终记录实名。
- 处理责任使用明确成员外键，不再保存含糊 actor JSON。
- 事件详情为已登录成员提供“反馈此事件”入口，并展示其有权查看的关联反馈；不再从 Workspace 首页创建反馈。
- 反馈事实、相关方回应、核实过程和结论原则上公开；第三方隐私、凭据和法律要求保护的信息仍按独立规则脱敏。
- 反馈处理结论不得覆盖原事件；需要改变权威业务状态时，必须调用对应领域 service，并以新的 `resolution_event` 记录结果。
- “我的事务”继续投影与当前成员有关的反馈处理、等待和最近结束状态，Workspace 首页删除旧“申诉状态与提交表单”。
- **BREAKING**：以 `/event-feedbacks` 和新 schema 替换 `/disputes`；Workspace Summary 以反馈字段替换旧申诉字段。

### 目标

- 用一个语义明确、以事件为锚点的统一反馈流程承载纠错、意见、投诉、举报、复核和风险。
- 让数据库字段、服务、事件账本、页面和公开契约使用一致的反馈术语。
- 清除未上线系统中的旧申诉兼容层和测试数据假设。

### 非目标

- 不把反馈处理结果直接实现为跨领域万能修改器。
- 不改变原事件内容或允许删除审计记录。
- 不把 `SystemEvent` 审计链作为用户反馈入口；它仍可作为证据引用。
- 不在本次实现匿名提交；限制身份展示不改变系统内部实名记录。

### 权限影响

已登录并绑定成员身份的用户可针对其有权查看的 `Event` 提交反馈。反馈及结果默认公开；提交人自行选择其身份展示范围。具备治理处理权限的成员负责核实和结案，相关方可查看反馈事实并正式回应。提交人不能借此公开第三方受保护信息。

### 数据影响

通过数据库迁移删除 `Dispute` 及其外键，创建 `EventFeedback` 及明确外键。现有开发、seed 和测试申诉数据不迁移；项目尚未上线，不提供兼容数据转换。

### 公开契约影响

删除 dispute schema/example 和 `/disputes` API，新增 event-feedback schema/example 和 `/event-feedbacks` API；相关 Event、Workspace Summary 和 OpenAPI 字段同步改名，属于破坏性契约变更。

## Capabilities

### New Capabilities

- `event-feedback`: 定义以可见 `Event` 为核心的反馈创建、隐私、处理、结果和事务投影行为。

### Modified Capabilities

无。

## Impact

- `core` 模型、迁移、服务、事件 payload、ID 生成、Admin、seed 与 world reset。
- Observer 事件详情、Dashboard、Workspace 事务投影和测试。
- Live OS API、serializer、OpenAPI、JSON Schema 和示例。
- sibling docs 的数据库、治理边界、产品、API、Admin 和开发说明。
- 无新增第三方依赖。
