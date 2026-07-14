# 观察台

观察台是 Live OS 面向普通观察者的只读入口。

成员报名/准入流程会同时写入 `core_system_event` 审计账本和脱敏公开 `core_event`。Observer 时间线展示的是公开 Event，不展示 contact、账号、内部用户 ID。公开 Event 包含 `submitted`（收到成员报名）、`admitted`（新成员已加入）和 `rejected`（成员报名未通过）三个阶段，使用脱敏公开名称，payload 不含隐私字段。

当前路径：

```text
/observer/
/observer/simulations/
```

Observer entrypoints are `http://127.0.0.1:20101/observer/` or `http://bigreal.local/observer/` for realworld, and `http://127.0.0.1:20102/observer/` or `http://bigsim.local/observer/` for simulation.

## 当前展示内容

当前页面是时间线指挥台式总览，首页优先回答：

- 社区现在是否稳定。
- 今天最严重的事件是什么。
- 当前容量还能不能继续接纳成员。
- 哪些岗位压力最高。
- 哪些争议还没处理。

页面结构：

- 左侧导航：总览、事件、任务、资源、成员、岗位、争议、事件流、数据日志。
- 左侧导航使用 daisyUI Drawer，默认折叠为标题区左侧的图标按钮。展开和收起只切换前端状态，不改变 URL、不刷新页面，也不影响数据读取。
- 中间主区域：核心指标和“今日事件时间线（实时指挥）”。
- 右侧风险栏：当前风险总览、容量评估、高负载岗位 TOP 3、待处理争议。
- 二级入口：全部任务、全部资源、成员概况和数据日志；其中任务、成员、争议和事件流只跳转到观察台页面内的只读区域，资源和数据日志只指向公开只读 API。

首页不展示超长任务表、成员表、资源表、黑底终端日志或原始 JSON。

观察台不提供进入 `/admin/` 的导航。运营动作归属 API、领域服务或 control 后台；观察台只负责公开状态展示和复盘。

## 公开仿真档案馆

`/observer/simulations/` 是面向访客的公开仿真档案馆。它不负责启动仿真，也不直接暴露内部 raw 归档包；它把已归档的 `SimulationSnapshot` 和 `SimulationSnapshotItem` 转换成访客可读报告。

公开报告第一版展示：

- 本次仿真的一句话结论。
- 关键发现。
- 计划修订方向。
- 仍需回答的问题。
- 标准化时间线。
- 快照编号、归档时间和短哈希。

内部 raw 归档路径、来源数据库名、成员隐私和内部备注不在公开页面展示。仿真启动、归档和 raw 校验仍归属 `/admin/simulation-lab/`。

公开页面只展示 `publication_status=public` 的快照。内部复盘或隐藏快照仍保存在 control DB 和 raw 归档包中，但不会进入访客档案馆。

当快照来自 `zero_start` 场景时，公开报告会把重点放在“一个发起人 -> 自媒体报名 -> 初筛 -> 候选/备用/拒绝/退出 -> 成员能力矩阵 -> 文件签署方矩阵 -> 启动门槛缺口”这条早期链路上，用于向访客展示项目不是从成熟团队开始假设，而是在逐轮推演中提前暴露招募、筛选、能力结构和可追责文件责任问题。

## 数据来源

页面直接读取 Live OS 权威表：

- `core_member`
- `core_task`
- `core_resource`
- `core_event`
- `core_dispute`
- `core_ledger_entry`
- `core_capacity_assessment`
- `core_project_plan`
- `core_plan_revision`
- `core_plan_node`
- `core_simulation_run`
- `core_plan_node_run_state`
- `core_simulation_failure`
- `core_plan_revision_proposal`
- `core_plan_change_set`
- `core_plan_change_operation`
- `core_simulation_snapshot`
- `core_simulation_snapshot_item`

观察台不直接读取 Simulation Engine 数据，也不绕过 Live OS 业务表。

当前时间线指挥台的指标、公开事件、资源预警、未关闭申诉、容量状态和主线任务来自 Live OS 权威表。没有对应数据时，主题层只显示空状态，不再注入固定演示数字或演示事件。

Observer 不再承载仿真控制动作。仿真实验启动和推进在 `/admin/simulation-lab/` 完成；Observer 只读取当前 URL 绑定 world 的运行结果并用于复盘。未绑定 simulation run 的单回合推进不会写入真实世界数据。

点击“自动跑到失败”在 `/admin/simulation-lab/` 完成，并创建一次 `SimulationRun`，按主线计划节点推进，直到触发预算、人力、技能、资源、依赖或人员状态失败。失败会生成 `SimulationFailure`、`PlanRevisionProposal`、`PlanChangeSet` 和 `PlanChangeOperation`。这些结果用于复盘和人工审核，不会自动改写主线计划。

观察台页面保持只读；仿真推进、运营处理和底层维护分别归属 `bigadmin.local/admin/simulation-lab/`、API/领域服务和 `bigadmin.local/admin/`。

## 当前限制

- 观察台读取页面仍是公开只读入口。
- 仿真推进和自动跑到失败动作已经要求治理权限。
- 仍未实现观察者、成员、治理成员之间的完整产品级登录和导航分层。
- 满意度、疲劳值等每日聚合指标还没有独立表。
- 当前是 Django Templates 服务端渲染，使用 Tailwind、daisyUI 和 HTMX。
- 自动模拟还没有连续播放、暂停继续、随机种子和多运行对比。

## 前端实现

观察台前端遵守 Django 静态资源体系：

- Tailwind 由 `django-tailwind` 管理。
- daisyUI 作为 Tailwind 插件配置在 `theme/static_src/src/styles.css`。
- 左侧导航使用 daisyUI Drawer 管理纯 UI 展开状态，不通过 Django view 或 URL query 参数保存。
- HTMX 由 `django-htmx` 提供 middleware 和模板标签。
- 编译后的 CSS 位于 `theme/static/css/dist/styles.css`。

## 主题模板

观察台通过主题系统渲染公众页面。当前主 fallback 主题是 `default_game`。

核心路径：

```text
templates/themes/default_game/dashboard.html
templates/themes/default_game/components/
templates/themes/default_game/partials/
static/themes/default_game/
```

主题上下文由 `observer.context_processors.theme_context` 注入，展示层数据契约由 `observer.dashboard_theme.build_dashboard_theme_context()` 提供。

完整规则见 `docs/theme-system.md`。

HTMX partial URL：

```text
/observer/dashboard/partials/missions/
/observer/dashboard/partials/events/
/observer/dashboard/partials/map-points/
/observer/dashboard/partials/task-detail/
/observer/dashboard/partials/risk/
/observer/dashboard/partials/capacity/
/observer/dashboard/partials/photo-stories/
```

公开仿真档案 URL：

```text
/observer/simulations/
/observer/simulations/{snapshot_id}/
```

修改观察台模板或 Tailwind class 后执行：

```bash
python manage.py tailwind build
```

## 验证

写入演示数据：

```bash
python manage.py seed_demo --world-id realworld
python manage.py seed_world simulation0001 --template demo
```

启动服务：

```bat
start.bat
```

访问：

```text
http://127.0.0.1:20101/observer/
```

自动化测试：

```bash
python manage.py test observer --settings=live_os.test_settings
```
