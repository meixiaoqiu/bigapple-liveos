# AI 开发指南

这份文档用于让 AI 编码助手和人类贡献者遵守同一套项目规则。

## 不可突破的边界

- Live OS 是权威系统。
- Simulation Engine 是 API 客户端。
- 先改 Contracts，再改实现。
- 产品规划按中远期完全体描述，当前实现只是阶段性切片。
- 积分账本只能追加，不能覆盖历史。
- 算法可以建议，但不能成为最终责任人。
- 治理处置必须保留具体实名责任人。
- **任何 Credential / NFT / Badge 相关功能不得绕过 RoleAssignment / RolePermission。** 权限判断只有一条路径：`Member → active RoleAssignment → RolePermission → Permission`。不得出现 `has_credential`、`has_nft`、`has_badge` 等直接授权路径。
- **注册与报名拆分后**：注册创建基础 Member + 基础角色；正式成员报名只申请更高角色和正式编号 Credential。Member 和 Role 的耦合只存在于 RoleAssignment 表，不存在于 Member 的字段标记。

## 修改代码前

1. 阅读 `README.md`。
2. 阅读 `../big-apple-contracts` 中相关 contract。
3. 阅读 `docs/` 下相关文档。
4. 先理解现有代码，再增加抽象。

## 编辑规则

- 字段名尽量和 contracts 保持一致。
- 会改变权威状态的 service 函数必须写 docstring。
- 含义不明显的 model 字段必须写 `help_text`。
- view 保持轻量，状态变化放进对应领域服务模块；不要再新增 `core.services` 这种大杂烩服务门面。
- 权威模型仍归属 `core` app，但模型定义必须按领域放在 `core.models` 包下；`core.models.__init__` 只是导出入口，不要重新写成大模型文件。
- 新增依赖前必须说明原因。
- 不要把密钥或真实隐私数据写入仓库。

## 必须同步更新的文档

| 变更 | 必须更新 |
| --- | --- |
| 新增或删除模型字段 | `docs/DATABASE_SCHEMA.md` |
| 项目执行计划、节点、依赖、需求或容量影响变化 | `docs/PROJECT_PLAN.md` 和 `docs/DATABASE_SCHEMA.md` |
| 自动模拟、失败反馈、计划修订建议或计划变更集变化 | `docs/SIMULATION.md`、`docs/PROJECT_PLAN.md` 和 `docs/DATABASE_SCHEMA.md` |
| API 路径或 payload 变化 | `docs/API.md` 和 contracts |
| 新业务流程 | `docs/ARCHITECTURE.md`、`docs/DEVELOPMENT.md`，必要时增加对应流程文档 |
| 任务、申诉、角色任命、提案、积分流水和统一事件账本之间的边界变化 | `docs/GOVERNANCE_INTERACTION_BOUNDARY.md`、`docs/ARCHITECTURE.md` |
| 产品角色、入口或中远期规划变化 | `docs/PRODUCT_PLANNING.md` |
| 路线图阶段、优先级或完成标准变化 | `docs/ROADMAP.md` |
| Django Admin 展示、权限或风险分层变化 | `docs/ADMIN.md` |
| 观察台 UI、HTMX partial、Tailwind/daisyUI 构建方式变化 | `docs/OBSERVER.md` 和 `docs/DEVELOPMENT.md` |
| AI 或模拟边界变化 | `docs/AI_DEVELOPMENT_GUIDE.md` |

## 当前实现注意事项

- 已安装本地虚拟环境依赖，但 `.venv` 不进入 Git。
- 已生成并应用 `core.0001_initial` 迁移。
- 后台界面已中文化；代码和 contracts 字段值仍保持英文标识。
- 当前 `/admin/` 是内部维护后台，不等同于中远期最终运营后台。
- 当前 Django Admin 配置按维护域拆分：`core.admin` 是自动发现入口，成员/角色在 `core.admin_identity`，提案在 `core.admin_proposals`，任务/资源/申诉在 `core.admin_operations`，只读历史和事件账本在 `core.admin_events`。底层、危险和兜底维护操作统一归 control 后台；world runtime 只保留成员工作台、观察台、报名入口和 API。
- 当前模型定义按领域拆分在 `core.models` 包：身份/角色在 `identity`，提案在 `proposals`，项目计划在 `planning`，仿真记录在 `simulation`，仿真快照归档在 `simulation_archives`，任务/积分/资源在 `operations`，事件账本在 `events`，申诉/容量在 `disputes`。`core.models.__init__` 只用于稳定导出。
- 治理内核不再保留 `core.governance` 大门面；统一事件账本、提案、权限和角色任命应分别从对应领域模块导入。
- 不要在业务代码中直接根据 Credential/NFT/Badge 判断权限。所有运行时权限判断必须通过 RoleAssignment / RolePermission。详见 `docs/ARCHITECTURE.md` Credential/NFT 章节。
- 当前本地开发拆为三个站点入口：`bigadmin.local` 使用 `live_os.settings_admin` 和 `live_os.urls_admin`，承载 control plane 的 `/admin/` 与 `/admin/simulation-lab/`；`bigreal.local` 使用 `live_os.settings_real` 和 `live_os.urls_real`，承载真实世界 runtime；`bigsim.local` 使用 `live_os.settings_sim` 和 `live_os.urls_sim`，承载仿真世界 runtime。
Real and simulation runtimes use the same root paths: `/workspace/`, `/observer/`, `/apply/`, `/apply/partner/`, `/api/v0.1/`. `/apply/` is the member application and account-registration entrypoint; the old `/apply/member/`, old world-prefixed route family, old `/member/` workspace route, and `/live-admin/` route have been removed and must not be used in product code or tests.
- 当前 `/workspace/` 是固定 world 的成员自助工作台，归属 `workspace` app。身份必须从当前登录账号绑定的 `Member` 推导，不要重新引入 `/members/{member_no}/workspace/` 这种按 URL 选择成员的页面入口。
- 当前 `/observer/` 是固定 world 的时间线指挥台式观察台，使用 Django Templates、Tailwind、daisyUI 和 HTMX partial。仿真实验启动和推进归属 control plane 的 `/admin/simulation-lab/`，观察和复盘归属对应 world runtime 的 observer；不能把命令行 runner 当成产品形态，也不能让 simulation 默认写真实世界数据。
- 当前项目执行计划已经数据库化，`bigapple001据点执行计划` 是主线任务线源头。不要把主线计划只写在 Markdown 或代码常量里。
- 当前资源供需匹配复用既有结构：`Resource` 是资源主档和当前库存缓存，`ResourceTransaction` 是只追加库存流水，`PlanRequirement.resource` 是计划需求指向库存台账的桥，`SupplierQuote` 是合作方报名对具体资源的报价。不要另起一套平行资源库；完整采购、定标和合同流程后续再在这层之上扩展。
- `seed_demo` 命令只做演示数据编排，具体演示数据写入逻辑放在 `live_os.demo_seed`；不要把演示数据写回 core 规则引擎。
- 当前自动模拟可以按主线计划跑到失败，并生成 `PlanRevisionProposal`、`PlanChangeSet` 和 `PlanChangeOperation`。仿真写入必须绑定明确的 world 数据库和 `SimulationRun`；不要让模拟直接改写真实 world 的 `ProjectPlan`、`PlanRevision`、`PlanNode`、任务、资源、积分或成员状态，必须先形成建议和结构化数据 patch，再由人审核。
- 积分流水和统一事件账本在 `/admin/` 中是只读历史记录；业务事件流、规则版本和容量评估不注册到 `/admin/`。
- 可以运行 `python manage.py seed_demo --world-id realworld` 写入指定 world 的后台预览用演示数据；运行时启用 world 数据库路由后，直接写入型命令不能依赖隐式默认 world。仿真 world 后台预览用 `python manage.py seed_world simulation0001 --template demo`；真正从一个发起人开始的仿真基线用 `python manage.py seed_world simulation0001 --template zero_start`。启用仿真 bootstrap admin 时，`zero_start` 的唯一初始发起人应是配置的真实登录成员。
- 可以运行 `python manage.py smoke_workflow --world-id realworld` 或 `--world-id simulation0001` 通过 HTTP API 验证目标 world 的第一条业务闭环。真实世界不会默认写入演示数据；需要本地演示数据时显式传入 `--seed-demo`，仿真 world 会自动使用 `seed_world`。
- 可以运行 `python manage.py run_simulation_smoke --world-id simulation0001` 验证仿真 world 的自动推演闭环：幂等初始化、创建 `SimulationRun`、自动推进主线计划、生成 turn / observer event / 失败反馈，并在启用 world 数据库路由时检查 `realworld` 关键表记录数不变。
- `python manage.py run_zero_start_simulation --world-id simulation0001 --hours 168` verifies zero-start social-media recruitment and launch-threshold closure. The simulation drives virtual subjects through the real fixed-world forms at `/apply/` and `/apply/partner/`; it must not bypass the view / form / service chain to create application members directly. After the launch threshold is satisfied, the same run enters `pre_engineering` and records candidate sites, grid pre-screening, conditional lease review, and responsibility-document milestones in `SimulationTurn.metadata`; do not create a parallel simulation command for this phase unless the model boundary genuinely changes.
- 可以运行 `python manage.py archive_simulation_run --world-id simulation0001 --run-id sim-run-xxx` 把已结束的仿真 run 归档为 control DB 中的 `SimulationSnapshot` / `SimulationSnapshotItem` 和文件系统中的原始归档包。原始归档包默认在 `var/simulation_archives/`，不进入 Git；归档后用 `python manage.py verify_simulation_snapshot snapshot-xxx` 校验 raw 文件哈希、manifest 和标准化索引。
- 已结束的仿真 run 在同一 world 启动下一轮前必须被人工处置：要么通过 `/admin/simulation-lab/` 或 `archive_simulation_run` 归档为快照，要么通过 `/admin/simulation-lab/` 或 `discard_simulation_run --reason "..."` 明确放弃归档。两种处置都会写入 control DB 的 `SimulationRunDisposition`；Django Admin `LogEntry` 只记录技术后台操作，不能替代仿真处置结论。
- 仍在 `running` 但已经确认没有继续价值的 run，应先在 `/admin/simulation-lab/` 详情页执行“中止本轮仿真”，状态变为 `aborted` 后再归档或废弃。
- 修改任务创建、发布、指派、关闭、领取、提交、验收、资源调整、申诉处理、仿真推进、账本、事件或 world 边界逻辑后，必须运行对应 app 测试；完整本地回归使用 `python manage.py test core live_os observer workspace simulation simulation_lab worlds --settings=live_os.test_settings`。
- 新增后台高风险动作（如清空世界数据、直接修改权威状态）必须测试 world 边界：不得对 `realworld` 生效，只允许作用 `world_type=simulation` 的 `active` world，且必须写入 control DB 的审计记录。
- 已实现最小 session 身份绑定：`User.username == Member.member_no` 代表成员本人，活跃治理成员或 staff / superuser 可执行运营写入。不要重新引入由 payload 或表单选择责任人的 actor 绑定。
- 观察台中的满意度、疲劳值等指标目前是占位值，后续需要每日指标表。
- 修改 observer 模板中的 Tailwind class 后，必须运行 `python manage.py tailwind build` 并提交编译后的 `theme/static/css/dist/styles.css`。

## World Routing Rule

Use fixed-world site URLs for business pages. The real world site is `bigreal.local`; the first simulation site is `bigsim.local`. `worlds.WorldRegistry` still maps world IDs to database aliases for control-plane commands and compatibility routing.

- Control plane: `http://bigadmin.local/admin/`
- Simulation lab: `http://bigadmin.local/admin/simulation-lab/`
- Real member workspace: `http://bigreal.local/workspace/`
- Real observer: `http://bigreal.local/observer/`
- Simulation member workspace: `http://bigsim.local/workspace/`
- Simulation observer: `http://bigsim.local/observer/`
- Legacy world-prefixed routes have been removed from runtime URLConfs; use fixed-world root paths in tests and product code.
- Default local database aliases are `default -> dev_big_control`, `realworld -> dev_big_real` and `simulation0001 -> dev_big_sim0001`; additional simulation aliases can be declared through `BIG_APPLE_WORLD_DATABASE_ALIASES` and matching `BIG_APPLE_{ALIAS}_DB_NAME` / `BIG_APPLE_{ALIAS}_DATABASE_URL`.

World database routing is now active outside tests. Do not assume business ORM reads use `default`: `core` defaults to `realworld` without request context, and world-scoped requests route `core`, `auth`, and `contenttypes` to the selected world alias. A world alias must be configured, listed in `WORLD_DATABASE_ALIASES`, and must not be `default`; misconfiguration fails closed instead of falling back to the control database. Tests use `live_os.test_settings`, which disables cross-database routing to keep unit tests single-database unless a test explicitly targets the router or world isolation.
