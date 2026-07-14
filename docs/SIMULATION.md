# 仿真与实验后台

## 边界

仿真能力拆成三层：

- `simulation`：自动推演机器，负责仿真规则和推进服务。
- `simulation_lab`：仿真实验后台，负责启动、推进和查看实验运行。
- `observer`：观察复盘界面，只展示真实或仿真运行结果，不负责手动推进。

仿真不能默认写入真实世界数据。任何会修改任务、库存、积分、成员状态或计划状态的仿真动作，都必须先绑定到明确的 world 数据库和 simulation run。未绑定 run 的单回合推进会被拒绝。

## 当前入口

```text
/observer/
/admin/simulation-lab/
POST /admin/simulation-lab/advance/
POST /admin/simulation-lab/run-until-failure/
```

Fixed-world `/observer/` observes the target world. Control-plane `/admin/simulation-lab/` starts and advances simulation experiments. `/admin/simulation-lab/run-until-failure/` is the current zero-start simulation entrypoint. `/admin/simulation-lab/advance/` is a legacy boundary self-check entrypoint marked as pending deprecation; it is not a simulation advance feature. If removed later, remove its URL, view, page button, and page-level test together.

## 自动跑到失败

`POST /admin/simulation-lab/run-until-failure/` 调用 `simulation.engine.run_active_plan_until_failure`。当前自动模拟规则：

1. 读取当前激活计划的已发布 `PlanRevision`。
2. 在当前 world 数据库中创建 `SimulationRun`，记录初始预算、可用人数、成员技能画像和平均疲劳值。
3. 为计划版本中的节点创建归属于该 run 的 `PlanNodeRunState`。
4. 按节点顺序推进非阶段节点；阶段节点只作为结构节点。
5. 每完成一个节点，记录 `SimulationTurn` 和带 `simulation_run_id` 的公开观察事件。
6. 遇到预算、人力、技能、资源、依赖、人员状态或责任闭环问题时，标记失败。
7. 失败会写入 `SimulationFailure`，并生成 `PlanRevisionProposal`。
8. 修订建议会生成 `PlanChangeSet` 和 `PlanChangeOperation`。
9. 建议和变更集只进入待审核状态，不会自动改写主线计划。
10. 人工采纳变更集后，系统复制源 `PlanRevision`，应用 `PlanChangeOperation`，生成新的计划版本。

## 写入规则

- 允许写入：当前 world 数据库中的 `SimulationRun`、`PlanNodeRunState`、`SimulationTurn`、`SimulationFailure`、`PlanRevisionProposal`、`PlanChangeSet`、`PlanChangeOperation` 以及带有 `simulation_run_id` 外键的公开观察事件；人工应用变更集时，允许在同一 world 数据库中生成新的 `PlanRevision` 和其下的计划节点、依赖、需求、容量影响。
- 不允许默认写入：真实 `Task` 状态、真实 `Resource.current_stock`、真实 `LedgerEntry`、真实成员状态、真实 `ProjectPlan` / `PlanRevision` / `PlanNode`。
- 自动模拟可以读真实计划和资源作为输入，但输出必须归属于目标 world 数据库和一次 simulation run；`generated_by = simulation_engine` 的 `Event` 必须绑定 `simulation_run_id`。
- 主线计划变更必须先形成结构化 patch 草案，再由人审核和明确应用；源计划版本不可修改。

## 当前限制

- 未绑定明确 world/run 的单回合推进会拒绝执行；当前自动跑到失败流程会创建具体 `SimulationRun`，不再维护单独的仿真世界表。
- 自动跑到失败是确定性规则，尚未引入随机种子、天气、质量返工、资源运输延误或多虚拟成员行为。
- 当前失败反馈只生成建议，不会自动克隆或发布新的计划版本；克隆和应用只能由管理员在审核后手动触发。

## 工程责任闭环

对 `C3 光伏一期 0.5MW` 这类现实工程节点，仿真不再只判断成员是否具备“光伏 / 电气 / 结构”技能。节点可以在 `PlanNode.metadata.required_responsibility_closures` 中声明必须取得的责任闭环文件，并在 `PlanNode.metadata.responsibility_documents` 中记录已取得文件。

责任文件通过条件至少包括：出具主体、文件名称、签字/盖章或合同责任、明确结论、适用于当前场地、适用于当前光伏规模；如存在限制条件，必须转化为后续施工约束。只有“专业人员评估通过”“顾问口头判断”或“成员经验判断”不能通过。

C3 默认要求：

- 结构/建筑安全责任文件
- 光伏系统设计责任文件
- 电气接入与并网责任文件
- 施工安全与质量责任主体
- 验收与归档责任安排

缺失时，失败类型为 `responsibility_closure_missing`，系统会生成“补齐光伏一期责任主体与责任文件”的计划修订建议和结构化变更集。变更集会建议增加并网预筛、场地合法性与附条件租赁审查、结构/建筑安全责任文件、光伏设计责任文件、电气并网责任文件、施工安全质量责任和验收归档责任等前置节点。

## 零起点自媒体报名与启动门槛仿真

`seed_world --template demo` 用于后台和观察台预览，不代表真实仿真起点。第二轮仿真的起点应更早：只有一个发起人，还没有成熟成员池、候选场地、任务、资源和完整计划。

第一版零起点切片使用 `zero_start` 模板：

```bash
python manage.py seed_world simulation0001 --template zero_start
python manage.py run_zero_start_simulation --world-id simulation0001 --hours 168
```

该流程会在目标仿真 world 中：

- 只预置一个发起人、一个极简 `ProjectPlan` 和一个已发布 `PlanRevision`。
- 按整数小时推进自媒体曝光、主动报名、初筛、候选、备用、项目拒绝和主动退出过程。默认 168 小时是压缩后的观察窗口，不是终局；报名密度不是平均分布，后续波次会随曝光积累逐步增加，用来模拟真实世界中从早期零星报名到后期集中增长的趋势。
- Virtual applicants and partners are no longer inserted directly by simulation code. The state machine chooses actions, then submits the real fixed-world application forms at `/apply/` and `/apply/partner/`.
- 当前第一版 driver 是 `http_form`：它会先 GET 报名页并检查关键 HTML 表单字段，再 POST 表单，让 view、form、service、事件账本和数据库写入走真实路径；它不执行浏览器 JS。后续可在同一 driver 边界接入 Playwright 抽样模式，让每类关键行为前 N 次走真实浏览器，其余大量重复样本走 HTTP form。
- 为每个虚拟小时记录 `SimulationTurn` 和公开观察 `Event`。每小时 payload 至少包含虚拟小时、状态机名称、表单 driver、成员/合作方报名增量、筛选增量、累计候选池、合作方状态、能力矩阵、文件签署方矩阵、当前阻塞项和下一步动作。
- 成员报名先写入 `MemberApplication` 并自动创建 `member_admission` 治理提案。仿真的候选/备用/拒绝/退出筛选结果写入 `metadata.screening_status`，不写入权威 `MemberApplication.status`。
- 合作方报名写入 `PartnerApplication`，用于记录服务能力、报价、资质说明、服务范围、限制条件和是否能出具责任文件。合作方不再只有少量固定线索；随着虚拟小时推进，系统会持续生成物流、设备报价、结构安全、光伏设计、电气并网、施工安全和验收归档等不同类型的合作方报名。
- 同时计算两张启动门槛矩阵：前 N 名成员需要补齐的实际能力，以及需要书面文件的合作伙伴/签署方。
- 每次 `--hours` 代表一个观察窗口，不是硬性终局。默认 168 小时只是把现实中的早期招募周期压缩成一段可观察窗口；如果成员能力矩阵或文件签署方矩阵仍未满足，系统会写入一条 `responsibility_closure_missing` 失败证据和修订建议，但 `SimulationRun` 保持 `running`，允许管理员继续推进下一个观察窗口。连续推进同一个 run 时会复用已有启动门槛变更集，避免每个观察窗口都生成重复的计划变更。
- 只有报名页面、表单字段、表单校验、服务保存或数据库写入这类系统交互链路失败时，零起点 run 才会进入终止性的 `failed` 状态，并要求先人工归档或废弃后再启动新 run。
- 生成“增加自媒体报名筛选与启动门槛矩阵”的 `PlanRevisionProposal`、`PlanChangeSet` 和 `PlanChangeOperation`。
- 对应 `PlanChangeOperation` 会以 `add_node` / `add_requirement` 形式描述可落入下一版 `PlanRevision` 的 Z0 节点、能力需求和文件责任需求。

这个切片的目的不是一次性模拟完整开荒，而是把“谁报名、谁被接纳、谁退出、能力矩阵是否成形、文件签署方是否到位”提前到 A0 抵达之前。能力需求只要求具备实际能力，例如做饭、视频剪辑、资料整理；文件需求必须有对应签署方，例如结构报告、电气并网方案、施工安全方案和验收归档资料。仿真失败也分两类：业务门槛失败表示报名和合作方质量不足；系统交互失败表示真实报名页、字段、校验或保存链路不能支撑仿真。后续应继续把成员抵达、食宿、任务承接、治理表决和工程责任文件取得都改成小时级状态机。

### 仿真分层

零起点仿真拆为三层，降低未来业务流程变化对仿真的连锁影响：

**Driver 层（`simulation/form_drivers.py`）：** 调用真实报名表单和服务（`/apply/`、`submit_member_application`）。负责把虚拟主体动作转化为真实系统写入，不直接做统计查询。

**Projection 层（`simulation/projections.py`）：** 读取真实状态和仿真 metadata，负责候选池、启动门槛 summary、能力覆盖、文件签署方覆盖、成员/合作方快照等 read-model 组装，为 Strategy 层提供稳定输入。
- `screening_status_for(application)` — 读取 `metadata.screening_status`
- `candidate_members_for_run(run, founder_member_no=...)` — 返回候选成员；传入 founder_member_no 时会把 founder 放在最前面
- `candidate_summary_for_run(run)` — 返回各类筛选状态的计数值

**Strategy/Scenario 层（`simulation/zero_start_strategy.py`、`simulation/zero_start.py`）：** 负责虚拟主体配置、报名时机、筛选规则、启动门槛需求常量等场景定义，以及小时级推进编排。筛选决策和需求配置集中在 `zero_start_strategy.py`，引擎编排保留在 `zero_start.py`。

`MemberApplication.status` 是权威准入状态（`admission_voting` / `admitted` / `rejected` / `withdrew` / `submitted`）。`metadata.screening_status` 是仿真筛选口径（`candidate` / `standby` / `rejected` / `withdrew`），两种状态机互不干扰。

## 仿真快照归档

一次仿真结束后，可以把 run 归档为永久快照：

```bash
python manage.py archive_simulation_run --world-id simulation0001 --run-id sim-run-xxx
python manage.py archive_simulation_run --world-id simulation0001
```

归档后可以随时校验快照包和查询索引：

```bash
python manage.py verify_simulation_snapshot snapshot-xxx
```

也可以在仿真实验后台选择仿真槽位、处置已结束 run、启动或继续零起点仿真：

```text
/admin/simulation-lab/
```

已归档快照、快照明细和处置记录的列表归属 Django Admin 首页的“仿真”一级菜单；实验后台只保留槽位选择、运行控制、待处置 run 详情审阅、归档、废弃和计划变更采纳这类独有操作。计划变更集归属于来源 run，统一在 run 详情页中审阅、采纳或弃用，不再作为首页独立列表展示。处理人可以在归档或废弃前查看失败证据、修订建议、结构化变更集和推进日志。

待处置 run 详情页还会显示每个 `PlanChangeSet` 的采纳状态。未采纳的仿真 world 变更集应在该页独立执行“采纳为下一轮仿真基线”；普通 Django Admin 不携带 world 数据库上下文，不能可靠审阅 simulation world 的变更集。这个动作会生成并发布新的 `PlanRevision`，退役同一计划下旧的已发布版本，并把 `PlanChangeSet.applied_revision` 指向它；它不会自动归档或废弃 run。

当前阶段至少一个仿真槽位就足够，例如 `simulation0001`。该槽位可以反复复用；每轮仿真结束后必须先归档为快照，或明确废弃并填写原因，才能启动下一轮。历史复盘不依赖永久保留该槽位中的运行态数据库，而依赖 control DB 中的快照索引、处置记录和文件系统 raw 归档包。

访客查看的公开仿真档案归属 Observer：

```text
/observer/simulations/
```

公开档案馆读取 `SimulationSnapshot` 和 `SimulationSnapshotItem`，生成可读报告、关键发现、修订方向和标准化时间线。它不展示 raw 归档路径、来源数据库名或内部备注；raw 包校验仍由内部 `/admin/simulation-lab/` 或 `verify_simulation_snapshot` 命令完成。

不传 `--run-id` 时，命令会归档该仿真 world 中最新一个已结束的 `SimulationRun`。归档只接受仿真 world，不接受 `realworld`。

归档命令可以写入正式档案字段：

```bash
python manage.py archive_simulation_run \
  --world-id simulation0001 \
  --run-id sim-run-xxx \
  --scenario zero_start \
  --purpose "验证从一个发起人开始的自媒体报名筛选链路" \
  --hypothesis "报名数量不等于启动门槛满足" \
  --review-conclusion "需要在报名表和初筛中提前识别能力矩阵和文件签署方矩阵" \
  --next-run-basis "第三轮继续细化报名状态机、能力矩阵和文件签署方矩阵"
```

每个已结束的仿真 run 在启动下一轮前必须被人工处置：

- `archived`：通过 `archive_simulation_run` 归档为 `SimulationSnapshot`，并自动创建 `SimulationRunDisposition`。
- `discarded`：通过 `discard_simulation_run` 明确放弃归档，并写明原因。

放弃归档示例：

```bash
python manage.py discard_simulation_run --world-id simulation0001 --run-id sim-run-xxx --reason "参数误设，作为调试运行放弃归档。"
```

这条规则的目的不是强制所有误运行进入公开历史，而是防止未复盘、未归档、未放弃的 run 被下一轮静默覆盖。Django Admin 自带 `LogEntry` 仍可记录管理员在 `/admin/` 的技术操作；`SimulationRunDisposition` 记录的是仿真历史生命周期的业务结论。

处于 `running` 的零起点 run，或旧版本留下的“启动门槛未满足”业务失败 run，都表示当前招募和合作方报名窗口还可以继续。实验后台会把运行控制切换为“继续当前仿真”和“中止当前仿真”，并在继续提交前弹出确认框。继续推进不会新建第二条 `SimulationRun`，而是在同一 run 下追加新的小时级 `SimulationTurn`、公开观察 `Event`、报名记录、失败证据和计划修订建议。

如果处理人确认某个 `running` run 因模型缺陷、参数误设或输入条件错误而没有继续价值，可以在 run 详情页执行“中止本轮仿真”。中止会把 `SimulationRun.status` 置为 `aborted`，写入中止原因、处理人和时间，并追加一条“人工中止本轮仿真”的 `SimulationTurn` 和公开观察 `Event`。中止后该 run 才进入可归档或可废弃状态。

应用计划变更集不是 run 生命周期处置。处理人可以先应用计划变更再归档，也可以只归档历史而不采纳变更；两者必须分别作出决定。下一轮仿真应显式选择或发布由变更集生成的新 `PlanRevision` 作为继续推演的基础。

归档分两层：

- `raw_archive`：原始归档包，默认写入 `var/simulation_archives/{snapshot_id}/`。它按模型逐表导出当前 world 数据库中的全部 `core` 域模型数据，并生成 `manifest.json`、逐表 SHA-256、raw 清单稳定哈希、迁移状态、代码版本和 `report.html`。这层数据作为原始证据，不应随业务模型演进而改写；校验命令会检查 raw 文件哈希、记录数、manifest 和 control DB 索引是否一致。
- `normalized_archive`：写入 control DB 的 `SimulationSnapshot` 和 `SimulationSnapshotItem`。它保存失败类型、失败节点、turn、event、proposal、change set 和 change operation 等查询索引。后续页面和统计优先读取这一层。

这意味着仿真 slot 数据库可以被清空复用；历史复盘依赖快照索引和原始归档包，而不是永久保留每次仿真的活数据库。

## 验证

```bash
python manage.py test simulation simulation_lab --settings=live_os.test_settings
python manage.py test simulation.tests.test_simulation_archive --settings=live_os.test_settings
```

## 仿真闭环 smoke

`run_simulation_smoke` 是开发自检命令，用于验证“指定仿真 world 初始化 -> 创建 simulation run -> 自动推进 -> 生成 turn / observer event / 失败反馈”这条闭环。

```bash
python manage.py run_simulation_smoke --world-id simulation0001
python manage.py run_simulation_smoke --world-id simulation0001 --max-turns 30 --skip-seed
```

这个命令只接受仿真 world，会拒绝 `realworld`。默认会先复用 `seed_world` 写入幂等演示数据，然后在该 world 中执行 `run_active_plan_until_failure`。它会校验：

- 只新增一次 `SimulationRun`。
- 产生 `SimulationTurn` 和绑定 `simulation_run_id` 的 `Event`。
- 生成每个计划节点的 `PlanNodeRunState`。
- 如果 run 失败，必须生成 `SimulationFailure`、`PlanRevisionProposal`、`PlanChangeSet` 和 `PlanChangeOperation`。
- 推进过程不新增任务、积分、成员、资源、主线计划、计划版本与计划节点记录。
- 启用 world 数据库路由时，检查 `realworld` 的关键表记录数不变。

零起点自媒体报名与启动门槛闭环使用：

```bash
python manage.py run_zero_start_simulation --world-id simulation0001 --hours 168
```

它同样只接受仿真 world，会校验每个虚拟小时的 `SimulationTurn`、公开观察 `Event`、成员报名申请、合作方报名申请、启动门槛观察证据、计划修订建议和结构化变更集。启动门槛未满足时 run 会保持 `running`，再次执行命令会继续推进同一个 run；系统交互链路失败才会终止为 `failed`。
