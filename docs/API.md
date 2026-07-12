# API 文档

API 前缀：

```text
/api/v0.1/
```

Fixed-world sites use root `/api/v0.1/`; real and simulation worlds are isolated by host and database.

契约源头：

```text
../big-apple-contracts/openapi/live-os.v0.1.openapi.json
```

## 公开接口数据边界

以下接口允许访客浏览公开仿真数据，但只返回 public-safe 投影：

- `GET /tasks`：返回任务的公开属性和状态，不返回 `assignee_member_no`、`submitted_at`、`reviewed_at`、`metadata`。
- `GET /resources`：返回资源库存和预警信息，不返回原始 `metadata`。
- `GET /events?visibility=public`：返回公开时间线信息，不返回 `involved_member_ids`、`related_dispute_id`、原始 `payload`；人工生成的公开事件只返回标题级 `summary`；保留 `related_task_id` 以便关联公开任务。
- `GET /observer/summary`：复用公开事件和公开资源投影，不返回原始事件 `payload` 或资源 `metadata`。

查询 `visibility=internal` 或 `visibility=private` 的事件仍需治理权限，并继续返回内部完整事件结构。`big-apple-contracts` 已用 `public-task`、`public-resource`、`public-event` schema 表达这些公开投影边界。

## 已实现路径

| 方法 | 路径 | 用途 | View |
| --- | --- | --- | --- |
| GET | `/members/{member_no}` | 获取单个成员。 | `live_os.api.members.get_member` |
| GET | `/members/{member_no}/workspace` | 获取成员工作台摘要。 | `live_os.api.members.get_workspace_summary` |
| GET | `/tasks` | 获取任务列表。 | `live_os.api.tasks.list_tasks` |
| POST | `/tasks/{task_id}/claim` | 领取开放任务。 | `live_os.api.tasks.claim_task_view` |
| POST | `/tasks/{task_id}/submit-labor` | 提交劳动说明和证据。 | `live_os.api.tasks.submit_labor_view` |
| POST | `/tasks/{task_id}/review` | 验收任务，验收通过时创建账本流水。 | `live_os.api.tasks.review_task_view` |
| GET | `/ledger-entries` | 获取积分流水。 | `live_os.api.ledger.list_ledger_entries` |
| GET | `/resources` | 获取资源状态。 | `live_os.api.resources.list_resources` |
| POST | `/disputes` | 创建实名申诉。 | `live_os.api.disputes.create_dispute` |
| GET | `/events` | 获取事件流。 | `live_os.api.events.list_events` |
| GET | `/capacity-assessments/latest` | 获取最新容量评估。 | `live_os.api.capacity.latest_capacity_assessment` |
| GET | `/observer/summary` | 获取观察台摘要。 | `observer.api_views.observer_summary` |

## 第一条业务闭环

```text
GET  /api/v0.1/tasks?status=open
POST /api/v0.1/tasks/{task_id}/claim
POST /api/v0.1/tasks/{task_id}/submit-labor
POST /api/v0.1/tasks/{task_id}/review
GET  /api/v0.1/ledger-entries?member_no=mem-0001
GET  /api/v0.1/events?simulation_day=1
GET  /api/v0.1/observer/summary
```

任务状态值来自 `../big-apple-contracts/schemas/task.schema.json`。当前支持：

```text
draft, open, claimed, in_progress, pending_review, accepted, rejected, disputed, closed, reversed
```

提交劳动后任务直接进入 `pending_review`。`closed` 表示运营人员在任务进入成员履约链路前关闭任务；它不会产生积分流水，也不等同于 `reversed`。

## 成员工作台最小读模型

P2 成员工作台使用聚合读接口：

```text
GET /members/{member_no}/workspace
```

对应页面：

```text
/workspace/
```

该接口不替代任务、账本、申诉或事件 API。它只是为成员工作台首屏提供聚合摘要，当前返回：

- 成员身份和画像。
- 当前模拟日期。
- 当前积分余额。
- 可领取任务。
- 成员当前任务。
- 个人任务历史。
- 近期积分流水。
- 近期相关事件。
- 未关闭申诉。
- 最近申诉状态详情。
- 低于预警线的资源。
- 任务状态计数。
- 下一步建议动作。

对应契约：

```text
../big-apple-contracts/schemas/member-workspace.schema.json
```

对应自动化覆盖：

- `live_os/api/tests/test_workflow.py`
- `python manage.py test core --settings=live_os.test_settings`
- `python manage.py smoke_workflow --world-id realworld --seed-demo`
- `python manage.py smoke_workflow --world-id simulation0001`

其中测试使用临时 SQLite 数据库；`smoke_workflow` 使用当前配置的目标 world 数据库，适合本地开发验证真实世界或仿真世界的 API 闭环。真实世界默认不写演示数据，只有显式传入 `--seed-demo` 或先运行 `seed_demo --world-id realworld` 才会具备演示起点；仿真 world 会自动使用 `seed_world` 准备隔离演示数据。

## 资源调整事件

当前资源调整先通过领域服务完成：

```text
core.resource_services.adjust_resource_stock(...)
```

该调用不是 contract-facing API；它是服务端领域边界。动作成功后会更新 `core_resource` 并追加 `event_type = resource` 的事件。外部客户端可以继续通过已实现 API 读取结果：

```text
GET /resources
GET /events
```

资源调整事件遵循 `../big-apple-contracts/schemas/event.schema.json`，资源状态遵循 `../big-apple-contracts/schemas/resource.schema.json`。

## 页面式仿真推进

当前仿真推进通过服务端渲染页面完成：

```text
GET  /observer/
POST /admin/simulation-lab/advance/
```

这些路径不是 contract-facing API；`GET /observer/` 是观察复盘界面，`POST /admin/simulation-lab/run-until-failure/` 是当前仿真实验后台表单动作。`POST /admin/simulation-lab/advance/` 是待遗弃的仿真写库边界自检入口，不是仿真推进功能；如果后续删除，应连同 URL、view、页面按钮和页面级测试一起删除。

推进一回合后，外部客户端仍通过既有契约读取结果：

```text
GET /tasks
GET /resources
GET /ledger-entries
GET /events
GET /api/v0.1/observer/summary
```

仿真写入的公开观察事件继续遵循 `../big-apple-contracts/schemas/event.schema.json`。仿真输出必须带有 simulation run 上下文；未绑定 run 的单回合推进不会生成真实任务、库存、积分或事件变更。

项目执行计划当前只通过服务端页面和 Admin 展示、编辑，不新增 contract-facing API。后续如果要让外部客户端读取或编辑计划，必须先在 `big-apple-contracts` 中定义计划相关 schema 和 OpenAPI 路径。

## 申诉处理事件

当前申诉创建有 contract-facing API：

```text
POST /disputes
```

成员工作台也提供页面动作：

```text
POST /api/v0.1/disputes
```

申诉处理先通过领域服务完成：

```text
core.dispute_services.start_dispute_review(...)
core.dispute_services.resolve_dispute(...)
```

这些调用不是 contract-facing API；它们是服务端领域边界。动作成功后会更新 `core_dispute` 并追加 `event_type = dispute` 的内部事件。外部客户端可以继续通过已实现 API 读取事件：

```text
GET /events
```

申诉状态遵循 `../big-apple-contracts/schemas/dispute.schema.json`，申诉事件遵循 `../big-apple-contracts/schemas/event.schema.json`。

## 当前安全状态

当前已实现最小 session 身份绑定：

- Django `User.username` 与 `Member.member_no` 相同时，视为该成员本人。
- staff / superuser 视为内部治理主体。
- 拥有相应 `governance.*` 权限的成员可访问运营、验收、资源、申诉和内部事件查询。
- 成员自助页面 `/workspace/` 要求当前登录账号绑定到目标 world 中的 `Member`；contract-facing 成员 API 仍按接口权限规则校验。
- 任务验收、运营处理、资源调整和申诉处理中的 actor 由服务端根据当前登录主体生成，不再信任 payload 或表单中的责任人字段。
- `POST /disputes` 只接受“提交申诉请求”，`dispute_id`、`status`、`handler`、`reviewer`、时间戳和最终结论由服务端管理。
- `GET /events` 默认只返回 `visibility=public`；查询 `internal` 或 `private` 事件必须具备治理权限。

当前仍不能直接用于生产。任何非本地部署前必须补齐：

- 面向外部客户端和 Simulation Engine 的非 cookie API token 或服务账号认证。
- 更细粒度的角色权限。
- schema 校验
- 审计中间件
- 登录、登出、密码和成员绑定管理页面

## 错误响应格式

错误响应遵循 contracts 中定义的基本错误形态：

```json
{
  "code": "state_conflict",
  "message": "Only open tasks can be claimed."
}
```
