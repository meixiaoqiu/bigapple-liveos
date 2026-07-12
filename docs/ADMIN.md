# Admin 内部维护后台

> 当前边界：`bigadmin.local/admin/` 是唯一 control 后台，承载底层、危险、会造成严重后果或需要兜底维护的操作。真实世界和仿真世界 runtime 不暴露 `/admin/`，也不再暴露 `/live-admin/`；成员侧统一使用 `/workspace/`。

## 定位

`/admin/` 是当前阶段的中文内部维护后台，用于开发、本地演示、排障和少量早期管理操作。

它不是中远期完全体里的最终运营后台。最终运营后台应按成员、任务、资源、申诉和审计流程组织页面；Django Admin 仍保留为底层维护工具。

当前本地开发已经拆成三个站点，但 Django Admin 只在 control plane 暴露：

- `bigadmin.local/admin/`：唯一 Django Admin / control plane，管理世界目录、仿真实验后台、仿真归档、底层数据和兜底维护。
- `bigreal.local/`：真实世界用户系统，不暴露 `/admin/`。
- `bigsim.local/`：仿真世界用户系统，不暴露 `/admin/`。

世界 runtime 不再提供独立运营后台。成员本人使用 `bigreal.local/workspace/` 或 `bigsim.local/workspace/`；底层、危险和兜底维护操作统一进入 `bigadmin.local/admin/`。

## 访问

启动服务：

```bat
start.bat
```

访问：

```text
http://127.0.0.1:20100/admin/
```

如果没有超级用户，先创建：

```bash
python manage.py createsuperuser
```

多数据库本地环境推荐用 `bootstrap_world` 创建首批账号：

```bash
python manage.py bootstrap_world --world-id realworld --control-password "..." --world-admin-password "..."
```

该命令会创建 control DB 的 `/admin/` 技术 root，并在目标 world DB 中创建一个 `is_staff=False`、`is_superuser=False` 的世界治理管理员成员。世界治理管理员的业务权限来自 `Member -> RoleAssignment -> RolePermission -> Permission`，不是来自 staff 或 superuser。

仿真 world 可以通过 `.env` 中的 `BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_*` 变量配置首个治理管理员账号。只有显式设置 `BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_ENABLED=true`，并同时提供用户名和密码时，`seed_world` 才会在成功初始化目标仿真 world 后复用 `bootstrap_world --skip-control-admin` 创建或更新该账号；模板占位密码 `CHANGE_ME` 会被拒绝。这样重置后的 `bigsim.local` 仍可用同一个成员账号登录 `/workspace/`。

写入演示数据：

```bash
python manage.py seed_demo --world-id realworld
```

## 模型风险分层

| 模型 | 当前 Admin 用途 | 当前保护 |
| --- | --- | --- |
| 成员 | 查看和维护成员角色、状态、画像、批次和积分下限。 | 禁止删除；已有记录的 `member_no` 只读。 |
| 成员报名、合作方报名 | 查看公开报名入口提交的成员和合作方申请，兜底排障表单、审核状态和仿真来源。 | 禁止删除；首页隐藏，日常审核入口后续应归属 world-scoped 审核流程。 |
| 组织、角色 | 维护组织结构和角色；权限作为角色能力在角色详情页维护。 | 禁止删除；提供搜索、筛选和外键自动补全。 |
| 角色任命 | 查看成员当前和历史角色任命。 | 禁止删除；关键动作会追加统一事件。 |
| 提案、投票和执行 | 作为业务流程对象保留底层维护入口，可在 control Admin 中查看和兜底维护。 | 禁止删除；关键动作会追加统一事件。 |
| 统一事件账本 | 在“技术审计与配置”中查看全系统关键事件哈希链。 | 禁止新增、修改和删除。 |
| 项目执行计划 | 维护主线计划名称、状态、目标地点和责任人。 | 禁止删除；已有记录的 `plan_id` 只读。 |
| 计划版本 | 维护计划版本、发布状态和变更说明。 | 禁止删除；已有记录的 `revision_id` 只读。 |
| 计划节点 | 维护阶段、里程碑、工程包、运营包、招募、抵达、容量门槛和扩容节点。 | 禁止删除；已有记录的 `node_id` 只读；可编辑成本、人力、工期、完成标准和容量影响。 |
| 计划依赖、计划需求、计划容量影响 | 维护节点依赖、预算、人力、材料、设备、空间、许可和容量变化。 | 禁止删除；已有业务 ID 只读。 |
| 模拟运行、节点模拟状态、模拟推进日志、模拟失败 | 查看当前 world 数据库中的自动模拟历史和失败原因。 | 禁止新增、修改和删除。 |
| 仿真快照、仿真快照明细、仿真运行处置记录 | 在“仿真”一级菜单中查看仿真归档和人工处置结论。 | 禁止新增、修改和删除；中止通过仿真实验后台完成，归档和放弃归档通过命令或仿真实验后台完成。 |
| 计划修订建议 | 查看由模拟失败生成的修订建议，标记审核状态。 | 禁止新增和删除；来源运行、失败和关联节点只读；审核状态可编辑。 |
| 计划变更集 | 查看由修订建议生成的结构化计划数据 patch，标记审核状态。 | 禁止新增和删除；来源运行、提案、计划版本和操作内容只读；审核状态可编辑；普通 Django Admin 不提供直接应用 action。 |
| 计划变更操作 | 查看变更集中每一条声明式计划数据操作。 | 禁止新增、修改和删除。 |
| 任务 | 查看和维护早期任务数据。 | 禁止删除；已有记录的 `task_id` 只读；提交和验收时间只读。 |
| 资源 | 查看当前资源库存，早期可做底层维护。 | 禁止删除；已有记录的 `resource_id` 只读；更新时间只读；库存调整应优先走 `core.resource_services`，以便生成资源事件。 |
| 申诉 | 查看早期申诉记录，必要时做底层维护。 | 禁止删除；已有记录的 `dispute_id` 只读；提交时间只读；申诉受理和处理结论应优先走 API 或 `core.dispute_services`，以便生成申诉事件。 |
| 规则版本 | 不注册到 `/admin/`；后续应通过专门规则发布流程创建新版本。 | 不通过 Django Admin 维护。 |
| 积分流水 | 在“技术审计与配置”中查看积分业务流水，并追溯统一事件。 | 禁止新增、修改和删除。 |
| 业务事件流 | 不注册到 `/admin/`；通过 API 和 `/observer/` 查看。 | 不通过 Django Admin 维护。 |
| 容量评估 | 不注册到 `/admin/`；通过 observer 查看当前 world 的容量状态。 | 不通过 Django Admin 维护。 |

## 操作原则

- Control Admin 首页按底层维护域分组：`技术审计与配置` 保留统一事件账本和积分流水，`仿真` 保留仿真快照、快照明细、处置记录和仿真实验后台入口；世界目录由 `worlds.WorldRegistry` 统一管理，不再保留独立的仿真世界模型。
- 在 control plane 中，成员、成员报名、合作方报名、组织、角色、角色任命、提案、任务、资源、供应商报价、库存流水、申诉、项目计划和仿真运行会作为底层数据管理模型展示。它们用于技术维护和兜底排障，不替代后续专门业务流程页。
- 真实世界和仿真世界不暴露 `/admin/`。所有 Django Admin 级底层管理都收敛到 `bigadmin.local/admin/`，避免 world 用户系统出现 `is_staff` 日常账号和 Django Admin 入口。
- 当前真实世界和仿真世界 runtime 只提供 `/workspace/`、`/observer/`、报名入口和 API，不暴露独立业务后台。底层维护、仿真实验和高影响操作归属 `bigadmin.local/admin/` 与 `bigadmin.local/admin/simulation-lab/`，其中仿真实验入口仅限 superuser。
- `Permission` 和 `RolePermission` 是底层能力目录，不作为日常顶层菜单展示；管理员主要从 `Role` 详情页通过角色权限 inline 查看和维护角色能力。
- 成员身份类型字段和单个 `Member.role` 字段已删除。成员当前身份和职责统一由 active `RoleAssignment` 表示；每个成员至少应拥有 `基础角色 / 大苹果成员`，成员可以同时拥有多个角色。
- 是否虚拟成员不再是成员字段，而由当前世界实例类型决定：`WORLD_INSTANCE_TYPE=simulation` 时 actor 输出为 `virtual_member`，`WORLD_INSTANCE_TYPE=real` 时 actor 输出为 `human_member`。
- 积分流水只能追加，不能通过 Admin 修改历史流水；正式创建和冲正应通过 `core.ledger_services.create_ledger_entry()` / `reverse_ledger_entry()`，并写入统一事件账本。
- 业务 `Event` 是给 API 和 observer 使用的可回放业务事件流，不注册到 Django Admin，也不能通过 Admin 修改历史事件。
- 统一事件账本是只追加哈希链审计依据，覆盖提案、投票、执行、角色任命、角色撤销、任务生命周期、申诉生命周期和积分变动，不能通过 Admin 新增、修改或删除；如需校验链路，使用 `core.event_ledger.verify_event_chain()`。
- 当前统一事件账本只是玩具版篡改可发现机制，不是绝对不可篡改存证；它没有外部锚定，数据库级写入或 ORM `update()` 仍可绕过 model/admin 保护，但链路校验应能发现不一致。
- 当前治理权限判断只走 `Member -> RoleAssignment -> RolePermission`。临时授权不再是独立模型，而是有较短 `end_at` 的角色任命；`resource=None` 表示不限定具体资源，只判断是否在任一资源范围具备该权限。
- 容量评估属于具体 world 的业务评估数据，不是 control DB 的全局技术配置。真实世界和仿真世界各自拥有自己的 `CapacityAssessment` 记录；observer 可展示摘要。重大容量决策应通过提案或专门流程落账。
- 规则版本属于具体 world 的业务规则数据，不是 control DB 的全局技术配置。真实世界和仿真世界各自拥有自己的 `Ruleset` 数据；后续规则变更应通过提案或专门规则发布流程创建新版本。
- 项目执行计划是主线任务线源头，可以在 Admin 中编辑，但模拟运行结果不能自动改写计划本体；后续应通过修订建议和计划版本处理。
- Django Admin 自带 `LogEntry` 记录管理员在 `/admin/` 中的技术增删改操作；它不能替代仿真业务处置记录。仿真 run 结束后必须通过 `SimulationRunDisposition` 留下 `archived` 或 `discarded` 结论，防止下一轮仿真静默覆盖未复盘数据。
- `/admin/simulation-lab/` 已纳入 Django Admin 登录和页面外壳，只允许 superuser 进入。该页面只保留仿真槽位选择、运行控制、待处置 run 审阅详情、中止、归档/废弃、计划变更集采纳、启动或继续零起点仿真，以及待遗弃的“仿真写库边界自检”入口；仿真快照、快照明细和处置记录的罗列查询归属 `/admin/` 的“仿真”一级菜单。计划变更集不在实验后台首页单独列表，统一放在来源 run 详情页中审阅、采纳或弃用。当前默认使用 `simulation0001`；同一槽位启动新 run 前必须先把已结束 run 归档或废弃，处置人记录当前 Admin 用户名。仍在 `running` 状态的零起点 run，或旧版本留下的“启动门槛未满足”业务失败 run，表示招募观察窗口可继续，后台按钮会显示为“继续当前仿真”并要求二次确认；如果确认本轮没有继续价值，应先在详情页或首页运行控制区“中止当前仿真”，再归档或废弃。`/admin/simulation-lab/advance/` 不是仿真推进功能；如果后续删除，应连同 URL、view、页面按钮和页面级测试一起删除。
- 计划修订建议和计划变更集来自模拟失败，只代表“建议”和“数据 patch 草案”。仿真 world 中的变更集应在 `/admin/simulation-lab/` 的 run 详情页审阅和采纳，因为普通 Django Admin 不携带 world 数据库上下文，不能可靠打开 simulation world 的 `PlanChangeSet`。采纳变更集时点击“采纳为下一轮仿真基线”；该动作复制源 `PlanRevision`，在新版本上应用操作，发布新版本，退役同一计划下旧的已发布版本，并把 `PlanChangeSet` 标记为 `applied`。它不等同于归档仿真 run。
- 任务创建、发布、指派、领取、劳动提交、验收和关闭的正式状态变化应优先通过 API 或 `core.tasks.*` 领域服务完成，这些服务会追加 `task_*` 统一事件账本记录。
- 申诉提交、受理和处理结论应优先通过 API 或 `core.dispute_services` 完成，这些服务会追加 `dispute_*` 统一事件账本记录。
- 当前 Admin 可以用于早期维护资源、供应商报价、成员和申诉数据，但涉及审计链的操作后续应迁移到运营后台。库存流水是只读查账记录，不能通过 Admin 新增、修改或删除。资源运营页会基于已发布计划需求、当前库存和有效供应商报价展示资源缺口，并展示近期库存流水；这不是完整采购系统，也不会自动创建采购单。
- Public application entrypoints on fixed-world sites are `/apply/member/` and `/apply/partner/`. Zero-start simulation submits these real forms; field, validation, or save-chain failures end the simulation run as a system-interaction failure. The first driver does not execute browser JavaScript yet; browser sampling should attach to the same flow later.

## 治理权限迁移

当前治理入口的主路径是 `Member -> RoleAssignment -> RolePermission -> Permission`。`core.access.user_has_governance_permission()` 会根据用户关联的 `Member` 检查角色能力；`基础角色 / 治理成员` 只是普通角色名，本身不再作为隐式权限 fallback。

基础治理权限 code：

- `governance.view_admin`
- `governance.manage_people`
- `governance.manage_organizations`
- `governance.manage_roles`
- `governance.manage_permissions`
- `governance.view_event_ledger`

初始化基础权限、组织和角色：

```bash
python manage.py init_governance_permissions --world-id realworld
```

该命令可重复执行，会在指定 world 中创建或复用 `大苹果治理组`、`治理管理员` 角色，并把上述权限绑定到该角色；它不会自动批量给 `基础角色 / 治理成员` 成员新增长期治理任命。运行时启用 world 数据库路由后，直接执行必须显式传入 `--world-id`。

也可以用命令把一个已有 `Member` 授予治理管理员角色：

```bash
python manage.py grant_governance_admin --world-id realworld --username alice
python manage.py grant_governance_admin --world-id realworld --member-no mem-0001
```

`grant_governance_admin` 会在指定 world 中自动确保基础权限、`大苹果治理组` 和 `治理管理员` 角色存在；重复执行不会重复创建 active 任命。新增任命会追加 `role_assigned` 统一事件。

给一个成员授予治理管理员权限的最小路径：

1. 在 Admin 中创建或确认 `Member`，并按需关联对应 Django `User`。
2. 运行 `python manage.py init_governance_permissions --world-id realworld`。
3. 在 `RoleAssignment` 中把该 `Member` 任命到 `大苹果治理组 / 治理管理员`。
4. 保持任命状态为 `active`；撤销、暂停或过期任命不会授予治理权限。

Admin 中的治理关系查看入口：

- `Member` 列表显示 `User`、显示名称、当前角色、状态和创建时间；详情页内联显示该成员的 `RoleAssignment`，也可直接新增角色任命。角色任命列表和 inline 会显示来源类型；由提案执行产生的任命会关联来源提案和执行记录。
- 成员账号绑定、当前角色任命、权限来源和任命历史当前通过 control Admin 兜底维护；后续专用业务页面应支持按 `member_no` 创建或绑定登录账号、重置密码、启停账号，以及授予或撤销生效中的角色任命。
- `Organization` 详情页内联显示组织下的 `Role`。
- `Role` 列表显示该角色绑定的权限数量，并可配置任命表决角色、通过比例和截止天数；详情页内联显示该角色绑定的 `RolePermission`，并显示当前拥有该角色的 `RoleAssignment`。
- `Proposal` 是通用治理提案入口；角色任命只是 `proposal_type=role_appointment` 的一种。流程是 `Proposal -> ProposalVote -> ProposalExecution -> SystemEvent`。
- 角色任命流程是 `role_appointment Proposal -> 表决通过 -> ProposalExecution -> RoleAssignment`。提案通过不等于执行完成，执行结果由 `ProposalExecution` 记录；投票资格以提案创建时的快照为准。
- `Permission` 和 `RolePermission` 仍保留为底层模型供角色 inline、自动补全和初始化命令使用，但不作为成员管理的顶层入口。
- `LedgerEntry` 是贡献积分业务流水，余额从 `posted` 流水汇总得到；冲正通过新的 `reversal` 流水表达，流水会关联到对应 `SystemEvent`，排序和审计顺序使用 `SystemEvent.seq`。
- `Task` 列表会显示来源类型，支持区分直接运营创建、提案执行、计划派生、仿真产生或系统规则产生的任务；由提案执行产生的任务会关联来源提案和执行记录。
- `SystemEvent` 是统一只读事件账本，只能查看 `seq`、事件类型、聚合对象、行为人、行为角色任命、发生时间和短 hash。后续专用业务页面可按聚合对象和事件类型提供只读汇总，便于区分提案、角色任命、任务、申诉、积分等事件分布。

## P1 强化范围

当前 P1 阶段已经强化：

- 列表页增加关键列，便于扫描任务、资源、申诉、事件和容量状态。
- 增加搜索、筛选、排序和日期层级。
- 外键字段使用自动补全，减少误选。
- 高风险历史模型设置为只读。
- 禁止从 Admin 删除核心权威记录。
- 新增治理主体、角色、通用提案和只读统一事件账本；权限能力从角色详情页维护。

## 演示数据场景

`python manage.py seed_demo --world-id realworld` 会写入一组幂等演示数据，用于快速预览 Admin 当前能力；仿真 world 推荐使用 `python manage.py seed_world simulation0001 --template demo` 显式绑定目标 world。重复执行不会重复插入同一批业务对象。

当前演示数据覆盖：

- 正常任务：已验收并产生贡献积分。
- 待验收任务：成员已提交劳动，等待管理员处理。
- 驳回任务：维修任务因证据不足被驳回。
- 争议任务：仓库盘点任务进入申诉复核。
- 冲正任务：重复采购登记产生原始流水和 reversal 冲正流水。
- 资源预警：药品库存低于预警线。
- 申诉状态：包含已提交、处理中、已解决三类申诉。
- 容量评估：包含暂停新增接纳的资源压力场景。
- 项目执行计划：包含 `bigapple001据点执行计划`、计划版本、30 个以上主线节点、节点依赖、预算/人力需求和容量影响。
- 现金资源和成员中文技能画像：用于自动模拟判断预算和技能缺口。

## 后续演进

当前已经启动自定义运营后台的第一条流程页：

```text
core.tasks.*
live_os.api.tasks
```

任务创建、发布、指派、关闭和验收相关状态变化通过 `core.tasks.*` 领域服务及 API 完成，不需要管理员直接编辑任务、积分流水和事件表。

当管理员需要频繁跨多个模型完成一个业务动作时，应继续扩展自定义运营后台，而不是继续扩展 Django Admin。

典型触发条件：

- 任务发布、领取、提交、验收需要在一个流程中完成。
- 资源变动应优先通过 `core.resource_services` 记录；该流程会更新库存并追加资源事件。后续仍需补独立操作日志。
- 申诉受理和处理结论应优先通过 API 或 `core.dispute_services` 记录；该流程会更新申诉状态，追加内部业务 `Event`，并追加 `dispute_*` 统一事件账本记录。后续治理后台仍需补高影响裁决和复核链。
- 不同管理员需要不同权限范围。
- 页面需要隐藏底层字段并展示业务上下文。

## Django Auth 与治理权限边界

- Django Admin 登录入口仍使用 Django 原生 `User.is_active`、`User.is_staff`、`User.is_superuser` 和 model permissions；治理权限不是 Admin 登录凭证。
- `superuser` 只作为技术 root、初始化和救急账号使用，不应批量授予日常治理人员。
- `is_staff=True` 只表示 control 技术账号可以进入 Django Admin 技术入口；它不等同于拥有大苹果业务治理权限。
- 普通世界治理管理员推荐账号状态是 `is_active=True`、`is_staff=False`、`is_superuser=False`，并通过 `Member -> RoleAssignment -> RolePermission -> Permission` 获得具体治理权限。
- `grant_governance_admin` 只授予 `Member` 的治理管理员角色任命，不会修改 `is_staff` 或 `is_superuser`。真实和仿真 world 不暴露 `/admin/`，所以业务治理账号不需要 `is_staff=True`。
- `core.access.user_has_governance_permission()` 的主路径是 `User -> Member -> RoleAssignment -> RolePermission -> Permission`。普通治理管理员应被授予 `治理管理员` 角色或其他绑定了 `governance.*` 权限的角色，不能只依赖 `基础角色 / 治理成员`。
- 当前 Django Admin 的模型增删改查权限仍主要依赖 Django model permissions；这意味着普通 staff 不会自动拥有所有模型权限，但精细到 `governance.*` 业务权限的 Admin 对象级控制仍是后续工作。
