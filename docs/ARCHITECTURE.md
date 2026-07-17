# 架构说明

## 目标

Big Apple Live OS 是社区运行的权威系统。

v0.1 必须保证真实用户和 Simulation Engine 使用同一套 API。Simulation Engine 是外部客户端，不是权威系统，不能直接修改业务表。

产品规划按照中远期完全体来描述，当前实现只是完整系统的阶段性切片。完整系统应同时服务观察者、成员、管理员、治理成员和 Simulation Engine；当前 Django Admin 只是内部维护入口，不代表最终运营后台边界。

治理交互模型遵循 `docs/GOVERNANCE_INTERACTION_BOUNDARY.md`：任务、申诉、角色任命、积分流水等具体业务保留自己的结构化模型；提案只作为需要共同决定时的决策机制；统一事件账本只记录已经发生的关键事实和责任链，不替代业务状态机。

## 仓库边界

本仓库负责：

- Django 应用代码
- 数据库模型和迁移
- Live OS API 实现
- 早期开发用 Django Admin 检查工具
- 数据库化项目执行计划模型
- Observer / Lab / Simulation 的边界：观察、实验控制和自动推演分离
- 证明 API 响应符合 `big-apple-contracts` 的测试
- Live OS 运行和开发文档

本仓库不负责：

- JSON Schema 或 OpenAPI 的源头定义
- Simulation Engine 行为模型
- 虚拟成员生成逻辑
- 生产密钥
- 真实成员隐私数据

契约源头位于相邻仓库：

```text
../big-apple-contracts
```

## 第一版形态

```text
HTTP client
  |
  v
live_os.urls_admin / live_os.urls_real / live_os.urls_sim
  |
  v
live_os.api.urls
  |
  v
live_os.api.* / workspace / observer / simulation_lab
  |
  v
workspace.context / core.tasks.* / core.dispute_services / core.resource_services / core.ledger_services / observer.* / simulation.engine
  |
  v
core.models.*
  |
  v
MySQL
```

当前默认运行入口分为三个站点：

- `bigadmin.local` / `live_os.settings_admin`：control plane。`/admin/` 是技术后台、原始数据和兜底维护入口；`/admin/simulation-lab/` 是仿真实验后台，负责启动、推进、归档和废弃仿真实验。
- `bigreal.local` / `live_os.settings_real`：真实世界 runtime。固定绑定 `realworld`，使用根路径 `/api/v0.1/`、`/observer/`、`/workspace/`、成员报名 `/apply/` 和合作方报名 `/apply/partner/`。
- `bigsim.local` / `live_os.settings_sim`：仿真世界 runtime。固定绑定 `simulation0001`，使用与真实世界相同的根路径和同一套页面/服务代码。

The old world-prefixed route family has been removed from runtime URLConfs. Real and simulation worlds are bound by fixed host settings, not by a world id in the URL.

固定 world runtime 的业务路由：

- `/api/v0.1/`：contract-facing JSON API。
- `/observer/`：面向观察者的观察复盘界面，只展示当前固定 world 的运行结果；`/observer/simulations/` 展示公开仿真档案和可读报告。
- `/workspace/`：面向当前登录成员的自助工作台页面。

当前代码边界：

- `core.models.identity`、`proposals`、`planning`、`simulation_runs`、`simulation_feedback`、`operations`、`events`、`disputes`：权威业务模型按领域拆分，但仍归属 `core` app，避免为了 app 名称重复造平行模型。
- `core.models`：稳定导出入口；新模型应进入对应领域文件，不要重新写回单个大文件。
- `live_os.api.*`：contract-facing JSON API 和 contract serializers，不承载页面模板，不放回 core 规则引擎。
- `core.access`：User / Member 到治理权限的纯权限桥接，不返回 HTTP response。
- `live_os.access`：Django request、页面 decorator、JSON 401/403 和 request actor 解析，供 API、workspace 和 simulation_lab 使用。
- `workspace.views`：成员自助工作台页面动作，身份来自当前登录账号绑定的 Member。
- `workspace.context`：成员工作台共享读模型，保持 HTTP-free，不放回 core 规则引擎。
- `observer.dashboard_context`、`page_context`、`timeline_context`、`simulation_reports`、`page_views`、`theme_views`、`api_views`：观察复盘读模型、公开仿真报告读模型、HTML/HTMX 页面、主题切换和观察摘要 API。
- `observer.theme.*`：观察端主题配置、当前主题 session、模板 fallback 和静态资源查找分离。
- `simulation.boundary`、`world_snapshot`、`run_state`、`run_progress`、`feasibility`、`failure_handling`、`feedback_suggestions`、`feedback_operation_handlers`、`feedback_operations`、`feedback_services`、`engine`、`ids`：仿真边界、真实世界只读快照、run/world 写入、节点推进、可行性判断、失败处理、计划反馈生成、失败类型操作生成、计划变更操作路由、反馈落库服务、推进循环和仿真记录 ID，不依赖 core 业务写服务。
- `simulation_lab.views`：仿真实验后台页面入口。
- `core.admin`、`admin_identity`、`admin_proposals`、`admin_operations`、`admin_events`、`admin_support`：Django 技术后台入口、成员/角色维护配置、提案维护配置、运营对象维护配置、只读事件账本配置和通用 Admin mixin。
- `core.event_ledger`、`event_payloads`、`governance_setup`、`role_assignment_services`、`core.proposals.*`、`permission_services`、`governance_signals`：统一事件账本、事件快照、基础治理权限初始化、角色任命、提案生命周期/投票/执行、角色权限判断和事件追加 signal。不要重新新增 `core.governance` 或 `core.proposal_services` 门面。
- `core.tasks.authoring`、`member_workflow`、`review`、`core.dispute_services`、`core.resource_services`、`core.ledger_services`：真实世界业务写操作。不要再新增 `core.services` 或 `core.task_services` 这种大杂烩服务门面。
- `live_os.demo_seed.*`：幂等演示数据写入逻辑，按项目计划、成员、资源、任务、事件、积分、申诉和容量评估拆分；`seed_demo` 命令只做编排。
- `simulation.admin`、`admin_planning`、`admin_runs`、`admin_feedback`：Django Admin 自动发现入口、项目计划维护配置、只读仿真运行记录配置和仿真反馈/计划变更配置。

项目执行计划位于任务系统之上：

```text
ProjectPlan / PlanRevision / PlanNode
  |
  v
Task / Resource / Event / CapacityAssessment
```

`ProjectPlan` 和 `PlanNode` 不替代 `Task`。它们回答"为什么要做这些任务、这些任务属于哪个主线目标、完成后增加哪些容量"。`Task` 仍负责具体可领取、可提交、可验收的工作。

`views` 应保持轻量：

- 解析请求 JSON
- 读取记录
- 调用 service
- 返回符合 contracts 的 JSON

`services` 负责状态变化：

- 领取任务
- 提交劳动
- 创建任务草稿
- 发布任务
- 指派任务
- 关闭未开始任务
- 验收任务
- 调整资源库存
- 记录资源事件
- 受理申诉
- 记录申诉处理结论
- 记录申诉事件
- 推进一回合页面式仿真，并将任务、资源和事件变化落回权威表
- 创建自动模拟运行，按项目执行计划推进到失败或完成
- 记录计划节点在模拟中的状态、失败原因和修订建议
- 把计划修订建议转化为结构化计划变更集和变更操作
- 创建积分流水
- 创建事件

`core.models.*` 负责持久化权威状态；`core.models` 包入口保留稳定导入面。

## 权威边界

Live OS 对以下数据拥有权威：

- 成员身份状态
- 任务状态
- 项目执行计划、计划版本、计划节点、节点依赖、节点需求和容量影响
- 积分账本流水
- 资源状态
- 申诉记录
- 规则版本记录
- 容量评估记录
- 事件流记录
- 自动模拟运行、节点模拟状态、模拟失败和计划修订建议
- 计划变更集和计划变更操作

Simulation Engine 可以：

- 调用 Live OS API
- 以虚拟成员身份提交请求
- 读取响应和事件流

Simulation Engine 不可以：

- 直接写入 Live OS 数据表
- 在 Live OS 外部结算最终积分
- 绕过任务验收
- 绕过申诉流程
- 绕过规则版本

Observer 不再负责仿真控制。仿真实验的启动和推进归属 `bigadmin.local/admin/simulation-lab/`；`bigreal.local/observer/` 和 `bigsim.local/observer/` 只负责观察和复盘各自固定 world，`/observer/simulations/` 负责把已归档仿真快照转成公开可读报告。`simulation` 服务可以读取真实计划和资源作为输入，但写入必须归属于明确的 world 数据库和 simulation run，不能默认修改真实任务、真实库存、真实积分或真实计划。

项目执行计划是模拟和真实执行都可引用的计划源头，不能只写在 Markdown 中。Markdown 只说明规则和边界；计划本体必须落库、可编辑、可版本化，并能被观察台和后续模拟运行引用。

自动模拟反馈遵循三层边界：

- 计划层：`ProjectPlan`、`PlanRevision`、`PlanNode` 记录当前权威计划。
- 模拟层：`SimulationRun`、`PlanNodeRunState`、`SimulationTurn`、`SimulationFailure` 记录当前 world 数据库中的某次模拟如何推进以及在哪里失败。
- 建议层：`PlanRevisionProposal` 记录从失败中得到的修订建议，等待人审核。
- 补丁层：`PlanChangeSet`、`PlanChangeOperation` 记录如果采纳建议，应如何修改计划数据库对象。

自动模拟可以生成失败、建议和结构化补丁，但不能直接改写计划层。采纳建议必须产生新的计划版本或人工可审计的计划变更。

## 当前限制

当前实现暂时不包含：

- 面向外部客户端和 Simulation Engine 的服务账号/API token 认证
- 细粒度角色权限
- API schema 校验中间件
- 完整成员工作台登录和账号管理
- 完整运营后台角色拆分
- 治理后台
- 复杂观察台交互
- HTMX 模板页面
- Celery 任务
- Redis
- 每日模拟快照表
- 独立仿真实验 ID 和随机种子表

## 长期架构完成清单

这份清单用于判断"边界是否真正清楚"，不是一次性必须完成的功能列表。

1. `core` 只承载底层规则、共享模型、权限、统一事件账本、API 合约和领域服务，不承载页面入口。
2. `bigadmin.local/admin/` 只作为 control plane 技术后台、原始数据查看、兜底维护和只读审计入口，不作为日常业务运营后台。
3. `bigreal.local/workspace/` 和 `bigsim.local/workspace/` 承载各自固定 world 的成员工作台，并走同一套页面和服务边界。
4. `bigreal.local/observer/` 和 `bigsim.local/observer/` 只负责观察、复盘和展示各自 world 运行结果，不提供仿真控制写入口。
5. `simulation` 只承载仿真推演逻辑；仿真写入必须绑定明确的 world 数据库和 simulation run，不能默认改写真世界任务、资源、积分、成员或计划。
6. `/admin/simulation-lab/` 承载仿真实验启动、配置、运行管理和实验结果管理，负责"怎么跑"，不负责手动干预真实业务过程。
7. 所有真实世界关键状态变化必须通过对应领域服务模块完成，并追加统一事件账本。
8. 任务、申诉、提案、积分流水等业务对象保留结构化表；统一事件账本记录关键事实、顺序、责任人和哈希链。
9. Django `User` 只作为登录账号；业务责任主体是 `Member`，权限来自 `Member -> RoleAssignment -> RolePermission -> Permission`。
10. `is_staff` / `is_superuser` 只属于 Django 技术后台边界，不能等同于业务治理权限。
11. Admin、服务、URL、文档和测试必须共同约束边界，避免后续把页面逻辑塞回 `core` 或让仿真误写真实世界。
12. 早期兼容门面和中间态命名应持续删除，不能因为"能跑"就长期保留。
13. 模型定义应继续按 `core.models` 领域文件维护；`core.models.__init__` 只能作为导出层，不能重新膨胀为单文件模型仓库。

## 身份体系

### 三层身份模型

```text
User          → 登录认证（Django auth）
Member        → 业务身份（所有注册用户的权威主体）
Role          → 权限集合（通过 RoleAssignment 授予）
Credential    → 公开事实证明（非权限来源）
```

1. **User 只负责登录认证。** `auth_user` 是 Django 的认证账号，承载 username / password / session。User 本身不表达任何业务权限，不存在"某个 User 天生有治理权"的概念。

2. **Member 是所有注册用户的业务身份。** 任何人通过 `/apply/` 注册后，系统立即创建 `Member` 记录。Member 是业务世界的唯一主体：领取任务、提交申诉、持有角色、获得 Credential 都以 Member 为锚点。Member 和 User 是一对一绑定关系。

3. **注册后自动获得基础角色。** 新注册 Member 即刻获得一个基础角色（如 `community_member`），该角色承载所有注册用户共有的最小权限（访问 workspace、维护公开资料、报名正式成员等）。不绑定基础角色的 Member 不能使用任何业务功能。

4. **正式社区成员只是更高权限角色之一。** "正式成员"不是一个新的 Member 记录，也不是一个新的 account——它只是 Member 获得了 `full_member` 角色。该角色通过 `member_admission` 提案投票通过后执行授予，在 RoleAssignment 表中留下一条活跃任命记录，并同时发放正式成员编号 Credential。权限检查只看 RoleAssignment 是否活跃，不查"是不是正式成员"这种硬编码标记。

5. **正式成员编号是一次性发放、永不复用的 Credential。**
   - 每个正式编号（如 `BA-0001`）全局唯一，只发放一次。
   - 成员退出后编号不回收、不重新分配给其他人。
   - 编号作为 `Credential Instance` 持久保留：它记录"谁在什么时间以什么方式成为正式成员"这一历史事实。
   - 编号自身不自动赋予任何权限——成员退出后 RoleAssignment 已撤销，编号只作为历史归属证明存在。

6. **RoleAssignment / RolePermission 是唯一运行时权限来源。** 所有 view、service、API 的权限判断必须走：

   ```text
   Member → active RoleAssignment → RolePermission → Permission
   ```

   不允许为 Credential / NFT / Badge 或 member_no 字符串编写第二套权限路径。`is_staff` / `is_superuser` 仅限 Django Admin 技术后台边界使用，不能等同于业务治理权限。

   **当前落地**：`workspace/context.member_has_full_workspace_access()` 和 `applications/views.member_is_formal_member()` 已基于 active `ROLE_FORMAL_MEMBER` + `SUSPENDED`/`EXITED` veto 实现。`Member.status` 不再作为权限来源。

### 注册与报名的拆分展望

当前实现中 `/apply/` 同时完成"注册 Member"和"发起正式成员报名提案"两个动作。长期架构下这两个动作应拆分为独立步骤：

1. **注册** → 创建 User + Member + 基础角色（`community_member`），可立即访问最小 workspace。
2. **报名正式成员** → 已注册 Member 提交申请，创建 `member_admission` 提案，通过后授予 `full_member` 角色并发放正式成员编号 Credential。

这一拆分依赖中远期报名流程重构，当前不做迁移。

## Credential / NFT / Badge 与权限边界

- **Credential / NFT / Badge 只能表示公开事实、荣誉、资格材料或历史证明。** 它们可以承载"某成员拥有某项资质/某 NFT"的公开信息，但不能被业务代码直接用来判定该成员是否有权执行某操作。
- **禁止出现** `if member.has_nft(...): allow_xxx` 或 `if member.has_credential(...): allow_xxx` 这类运行时授权路径。
- Credential / NFT / Badge 可以作为**授予 RoleAssignment 的依据**（例如治理提案决议"持有 X NFT 的成员获得治理角色"），但链上状态必须先导入/验证为系统记录，再通过治理规则或同步服务生成 RoleAssignment。应用运行时仍只查 RoleAssignment / RolePermission，不直接查询 NFT 所有权或 Credential 持有情况。
- 如果未来链上 NFT 上线，必须经过导入层写入链上证据表，再由治理流程授予相应角色。运行时权限链始终保持：`Member → active RoleAssignment → RolePermission → Permission`。
- Credential Template 与 Credential Instance 是未来可治理对象：社区成员可通过提案创建模板（如"年度贡献者"证书），治理流程核准后按模板发放实例。发放本身是一个有审计记录的业务动作；发放后是否影响权限，必须通过另一份提案授予 RoleAssignment。



## World Database Boundary

Long-term world isolation uses database boundaries instead of adding `world_id` to every business row.

- The canonical member entries are `bigreal.local/workspace/` and `bigsim.local/workspace/`.
- World-prefixed routes have been removed from runtime URLConfs; fixed-world hosts are the only supported product and test entrypoints.
- `worlds.WorldRegistry` is the control-layer world directory. It records `world_id`, type, database alias, database name and lifecycle status.
- The control database owns world routing metadata, `/admin/` technical accounts and technical session state.
- Each world database owns its own `auth_user` and business tables, so real and simulation worlds can run through the same application code path.
- Default local database aliases are `default -> dev_big_control`, `realworld -> dev_big_real` and `simulation0001 -> dev_big_sim0001`; additional world aliases declared in `BIG_APPLE_WORLD_DATABASE_ALIASES` are converted into Django `DATABASES` entries at startup.
- World binding is fail-closed: an active world must point to a configured, non-`default` alias listed in `WORLD_DATABASE_ALIASES`. A missing or control-database alias is treated as a configuration error instead of falling back to `default`.
- World lifecycle commands manage the control registry: `create_world` registers a configured world alias, `migrate_world` runs migrations for one active world, `seed_world` initializes an active simulation world from a safe idempotent template, `archive_world` disables a non-real world, and `delete_world` marks an archived non-real world as deleted.
- These commands do not create or drop physical MySQL databases. Physical database creation, backup, archival and dropping remain infrastructure operations.
- `seed_world` does not copy `realworld` data. The first supported template is `demo`, which reuses the existing idempotent `seed_demo` data under the selected simulation world context.
- `realworld` and every `world_type=real` row are protected from archive and delete commands.
- Fixed-world sites use root `/workspace/` paths. The URLConf no longer exposes compatibility world-prefix routes, `/live-admin/`, or the old `/member/` workspace route.

## World Auth Boundary

`auth_user` is migrated into each world database so real and simulation worlds use the same login and authorization logic. `django_session` is also migrated into each world database because split runtime settings (`live_os.settings_real`, `live_os.settings_sim`) run with the world database as `default` and no routers; the `bigreal` and `bigsim` login flows write session rows there. Under routed admin settings (`live_os.settings_admin`), `WorldDatabaseRouter` still routes session reads and writes to the control `default` database, while `allow_migrate` permits `sessions` migrations on world aliases so `migrate_world` creates the table required by split runtime sites. The world login form writes the selected `world_id` into session state, and middleware prevents that session from being reused across a different world.
