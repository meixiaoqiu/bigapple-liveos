# 数据库表结构

本文档描述 Live OS 第一阶段的数据表。任何 model 或 migration 变化，都必须同步更新本文档。

当前物理数据库由 `DATABASE_URL` 或本地 env 文件配置：

```text
.env
DATABASE_URL=mysql://用户名:URL编码后的密码@主机:3306/数据库名?charset=utf8mb4
```

## 命名规则

- 表名使用 `core_` 前缀。
- 主键使用 contracts 中的业务 ID，例如 `mem-0001`、`task-0001`。
- 面向 contract 的字段名尽量贴近 JSON payload。
- JSON 字段只用于 v0.1 中确实需要弹性的 metadata、模拟画像、风险指标等。

## core_member

成员权威记录。Django `User` 只负责登录账号；`Member` 才是大苹果治理主体。成员身份类型、是否虚拟成员和单个 `role_id` 字段已删除，成员角色统一由 active `RoleAssignment` 表示。每个成员至少应拥有 `基础角色 / 大苹果成员`，并可同时拥有多个角色。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | integer pk | 是 | 数据库内部主键。 |
| `member_no` | string unique | 是 | 稳定业务编号，例如 `mem-0001`。 |
| `user_id` | fk | 否 | 关联 Django 登录用户。 |
| `display_name` | string | 否 | 显示名称。 |
| `status` | enum string | 是 | 成员准入和生命周期状态。 |
| `batch_id` | string | 否 | 准入批次或模拟批次。 |
| `joined_simulation_day` | integer | 否 | 模拟中进入据点的日期。 |
| `credit_floor` | integer | 是 | 该成员类别允许的最低积分。 |
| `profile` | json | 是 | 模拟画像，例如疲劳值、满意度、技能等。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `metadata` | json | 是 | 扩展对象。 |

常用成员状态包括 `active`、`pending_training`、`pending_review`、`admitted`、`application_rejected`、`suspended`、`exited`。`pending_review` / `application_rejected` 账号只能进入最小报名工作台，业务权限仍由成员状态和角色权限共同限制。

## Auth/Admin 权限边界

Django `User` 仍只负责技术登录和 Admin 入口控制：`is_active` 控制账号是否可用，`is_staff` 控制是否可进入 Django Admin，`is_superuser` 是技术 root / 初始化 / 救急账号。日常治理人员不应被批量设置为 superuser。

大苹果业务治理权限由领域模型判断，主路径是 `User -> Member -> RoleAssignment -> RolePermission -> Permission`。临时授权不再是独立模型，而是有较短 `end_at` 的角色任命。`基础角色 / 治理成员` 只是普通角色名，本身不再授予治理权限；治理权限必须来自 `RolePermission`。

普通世界治理管理员推荐账号状态是 `is_active=True`、`is_staff=False`、`is_superuser=False`，并拥有有效 `Member`、`RoleAssignment` 和对应 `Permission`。`grant_governance_admin` 只创建或复用治理管理员角色任命，不会修改 `is_staff` 或 `is_superuser`；真实和仿真 world 不暴露 `/admin/`，业务治理账号不需要 Django staff 权限。

成员是否虚拟不再是成员字段，而由当前世界实例类型决定：`WORLD_INSTANCE_TYPE=simulation` 时 actor 输出为 `virtual_member`，`WORLD_INSTANCE_TYPE=real` 时 actor 输出为 `human_member`。当前默认值是 `simulation`。

## core_member_application

MemberApplication stores public member applications. Real and simulation worlds submit the same fixed-world form at `/apply/`; submission creates the login account and a minimal pending `Member` immediately, while formal admission is decided by governance proposal execution.

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `application_id` | string pk | 是 | 成员报名 ID。 |
| `applicant_name` | string | 是 | 报名人名称。 |
| `contact` | string | 是 | 联系方式。 |
| `motivation` | text | 是 | 报名动机。 |
| `availability_hours_per_week` | integer | 是 | 历史兼容字段；当前表单用可参与时段表达投入时间。 |
| `role_gap` | string | 否 | 报名人选择的当前角色缺口，例如 `settled_resident`、`service_resident`、`developer_ai_engineer`。 |
| `availability_slots` | json | 是 | 可参与时段数组，例如 `any_time`、`off_hours`、`weekend`；`any_time` 与其它时段互斥。 |
| `capability_scores` | json | 是 | 历史兼容和仿真字段；当前个人报名页不再展示能力自述输入。 |
| `can_issue_responsibility_documents` | boolean | 是 | 历史兼容字段；当前个人报名页固定为否，责任文件能力由合作方/机构报名承担。 |
| `document_authority_domains` | json | 是 | 历史兼容字段；当前个人报名页不再采集责任文件领域。 |
| `status` | enum string | 是 | `submitted`、`admission_voting`、`admitted`、`rejected`、`withdrew`。旧状态 `under_review`/`candidate`/`standby` 已迁移到 `admission_voting`。 |
| `requested_member_no` | string | 否 | 期望成员编号；仿真会写入稳定候选编号。 |
| `account_user_id` | fk | 否 | 成员报名时创建或复用的登录账号；提交后绑定到最小权限成员身份。 |
| `linked_member_id` | fk | 否 | 提交后创建或复用的最小权限 `Member`。 |
| `dynamic_answers` | json | 是 | 动态 textarea 问答数组，元素包含 `key`、`label`、`type`、`answer`。 |
| `frozen_at` | datetime | 否 | 报名提交并二次确认的时间；业务入口不提供提交后的撤回或修改。 |
| `admission_proposal_id` | fk | 否 | 接纳该申请者为正式成员的治理提案。 |
| `decided_by_id` | fk | 否 | 决议人（执行准入或提案拒绝的治理成员）。 |
| `submitted_at` | datetime | 是 | 提交时间。 |
| `decided_at` | datetime | 否 | 决议时间（准入执行或拒绝的时间）。 |
| `metadata` | json | 是 | 扩展数据；仿真会写入 `simulation_run_id`、`simulation_hour`、`driver_mode` 和 `external_ref`。 |

提交会创建登录账号、创建或复用 `status=pending_review` 的最小权限 `Member`、自动创建 `member_admission` 治理提案，并追加 `member_application_submitted` 统一事件。当前个人报名页按 steps 分步展示：第一步只采集 `role_gap` 和 `availability_slots`，第二步采集账号、密码、称呼、联系方式，第三步采集报名理由选项和可选的其他理由；不再向个人采集能力自述或责任文件能力。拒绝后同一账号可以再次提交一条新申请；提交成功后不可撤回或修改。正式接纳通过关联的 `member_admission` 提案投票并执行完成，执行后才把报名状态改为 `admitted`、把成员状态改为 `admitted` 并授予正式成员角色。准入执行或提案拒绝会追加 `member_application_reviewed` 统一事件。

## core_partner_application

PartnerApplication stores public partner applications from suppliers, institutions, professionals, and other service or responsibility-file providers. Real and simulation worlds submit the same fixed-world form at `/apply/partner/`.

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `application_id` | string pk | 是 | 合作方报名 ID。 |
| `organization_name` | string | 是 | 合作方名称。 |
| `contact_name` | string | 是 | 联系人。 |
| `contact` | string | 是 | 联系方式。 |
| `service_domains` | json | 是 | 服务、能力或资质领域。 |
| `can_issue_responsibility_documents` | boolean | 是 | 是否能出具可归档、可追责、可作为决策依据的书面文件。 |
| `responsibility_document_domains` | json | 是 | 可签署或盖章承担责任的文件领域。 |
| `qualification_summary` | text | 否 | 资质说明。 |
| `quote_summary` | text | 否 | 报价说明。 |
| `service_area` | string | 否 | 服务地区。 |
| `delivery_cycle_days` | integer | 否 | 交付周期天数。 |
| `constraints` | text | 否 | 限制条件。 |
| `status` | enum string | 是 | `submitted`、`under_review`、`qualified`、`standby`、`rejected`、`withdrew`。 |
| `reviewed_by_id` | fk | 否 | 审核人。 |
| `submitted_at` | datetime | 是 | 提交时间。 |
| `reviewed_at` | datetime | 否 | 审核时间。 |
| `metadata` | json | 是 | 扩展数据；仿真会写入 `simulation_run_id`、`simulation_hour`、`driver_mode` 和 `external_ref`。 |

提交会追加 `partner_application_submitted` 统一事件；审核会追加 `partner_application_reviewed` 统一事件。第一版不单独创建 `Partner` 主数据表，合作方池先由申请表承载；只有已审核且能出具责任文件的合作方才可覆盖启动门槛中的文件签署方需求。

## core_organization

治理组织容器，只表达容器和层级。组织不再保存类型；治理含义由角色、角色任命和角色权限表达。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | integer pk | 是 | 内部主键。 |
| `name` | string | 是 | 组织名称。 |
| `parent_id` | fk self | 否 | 上级组织。 |
| `status` | enum string | 是 | `active`、`inactive`、`archived`。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `updated_at` | datetime | 是 | 更新时间。 |

## core_role

组织下的角色，例如电工、仓库管理员、安全委员、群落管理员。系统会创建 `基础角色` 组织承载成员基础角色，包括 `大苹果成员`、`观察者`、`贡献者`、`预备成员`、`正式成员` 和 `治理成员`。真实世界和仿真世界使用同一套角色语义，是否仿真只由当前 world / actor 上下文表达，不再通过单独的 `仿真成员` 角色表达。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | integer pk | 是 | 内部主键。 |
| `organization_id` | fk | 是 | 所属组织。 |
| `name` | string | 是 | 角色名称。 |
| `description` | text | 否 | 角色说明。 |
| `status` | enum string | 是 | `active`、`inactive`、`retired`。 |
| `appointment_electorate_role_id` | fk self | 否 | 任命此角色时由哪个角色参与表决。 |
| `appointment_required_percent` | integer | 是 | 任命通过比例，50 表示过半，100 表示全票通过。 |
| `appointment_deadline_days` | integer | 是 | 默认任命表决截止天数。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `updated_at` | datetime | 是 | 更新时间。 |

约束：同一组织下 `name` 唯一。

## core_permission

领域治理权限定义，独立于 Django 内置 model permission。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | integer pk | 是 | 内部主键。 |
| `code` | string unique | 是 | 权限代码，例如 `access.warehouse`。 |
| `name` | string | 是 | 权限名称。 |
| `category` | string | 是 | 权限分类，例如 `access`、`grant`、`view`。 |
| `description` | text | 否 | 权限说明。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `updated_at` | datetime | 是 | 更新时间。 |

基础治理权限由 `python manage.py init_governance_permissions --world-id realworld` 幂等初始化：

| code | 说明 |
| --- | --- |
| `governance.view_admin` | 允许访问治理和运营维护入口。 |
| `governance.manage_people` | 允许维护成员治理主体。 |
| `governance.manage_organizations` | 允许维护治理组织容器。 |
| `governance.manage_roles` | 允许维护角色和任命。 |
| `governance.manage_permissions` | 允许维护权限定义和角色权限绑定。 |
| `governance.view_event_ledger` | 允许查看只追加统一事件账本。 |

初始化命令会创建或复用 `大苹果治理组` 组织、`治理管理员` 角色，并通过 `core_role_permission` 绑定上述基础权限。它不会自动批量授权成员；需要治理权限的成员应被显式任命到绑定了相应权限的角色。

可以用 `python manage.py grant_governance_admin --world-id realworld --username <username>` 或 `--world-id realworld --member-no <member_no>` 把一个已有 `Member` 授予 `治理管理员` 角色。该命令会复用基础权限初始化逻辑，重复执行不会重复创建 active `RoleAssignment`；首次创建任命时会追加 `role_assigned` 统一事件。运行时启用 world 数据库路由后，直接执行必须显式传入 `--world-id`。

## core_role_assignment

成员被任命到角色的记录。撤销时更新状态，不删除记录。成员可以同时拥有多个 active 角色；同一成员不应重复拥有同一个 active 角色。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | integer pk | 是 | 内部主键。 |
| `member_id` | fk | 是 | 被任命成员。 |
| `role_id` | fk | 是 | 角色。 |
| `status` | enum string | 是 | `active`、`revoked`、`suspended`、`expired`。 |
| `start_at` | datetime | 是 | 开始时间。 |
| `end_at` | datetime | 是 | 结束时间；所有角色任命必须有结束时间。 |
| `granted_by_id` | fk | 否 | 任命人。 |
| `revoked_by_id` | fk | 否 | 卸任处理人。 |
| `source_type` | enum string | 是 | 来源类型：`direct`、`proposal`、`initialization`、`system`。 |
| `source_proposal_id` | fk | 否 | 如果该任命由提案执行产生，关联来源提案。 |
| `source_proposal_execution_id` | fk | 否 | 如果该任命由提案执行产生，关联具体执行记录。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `updated_at` | datetime | 是 | 更新时间。 |

新增记录会追加一次 `role_assigned` 统一事件；状态从 `active` 变为 `revoked` 时追加一次 `role_revoked` 统一事件。普通字段编辑不会重复追加任命或卸任事件。事件 payload 会包含 `source_type`、`source_proposal_id` 和 `source_proposal_execution_id`，用于区分直接任命、提案执行、初始化或系统规则产生的任命。

## core_proposal

通用治理提案。成员准入和角色任命都不保留平行表决结构，分别使用 `proposal_type=member_admission` 和 `proposal_type=role_appointment`。后续规则、政策、预算、项目、声明等也复用同一套 `Proposal -> ProposalVote -> ProposalExecution -> SystemEvent` 流程。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | integer pk | 是 | 内部主键。 |
| `proposal_no` | string unique | 是 | 可读提案编号，例如 `0001`。 |
| `title` | string | 是 | 提案标题。 |
| `body` | text | 否 | 提案正文。 |
| `proposal_type` | enum string | 是 | `member_admission`、`role_appointment`、`role_revocation`、`rule`、`policy`、`budget`、`project`、`statement`。 |
| `status` | enum string | 是 | `draft`、`voting`、`passed`、`failed`、`cancelled`、`executed`。 |
| `proposer_member_id` | fk | 否 | 提案人。 |
| `proposer_role_assignment_id` | fk | 否 | 提案时角色身份；后台会按已选择的提案人过滤为该成员拥有的角色任命。 |
| `organization_id` | fk | 否 | 提案所属组织。 |
| `voter_scope_type` | enum string | 是 | `role`、`organization`、`all_members`。 |
| `voter_scope_role_id` | fk | 否 | 以某个角色作为投票范围。 |
| `voter_scope_organization_id` | fk | 否 | 以某个组织作为投票范围。 |
| `eligible_voters_snapshot_json` | json | 是 | 提案开始时冻结的投票资格成员快照。 |
| `pass_ratio` | integer | 是 | 通过所需赞成比例，1 到 100；`50` 表示严格超过 50%，例如 2 人需 2 票、4 人需 3 票。 |
| `quorum_count` | integer | 是 | 最低参与人数。 |
| `allow_vote_change` | boolean | 是 | 截止前是否允许改票。 |
| `start_at` | datetime | 是 | 投票开始时间。 |
| `deadline_at` | datetime | 是 | 投票截止时间。 |
| `passed_at` | datetime | 否 | 通过时间。 |
| `failed_at` | datetime | 否 | 失败时间。 |
| `cancelled_at` | datetime | 否 | 取消时间。 |
| `executed_at` | datetime | 否 | 执行完成时间。 |
| `payload_json` | json | 是 | 提案业务载荷。 |
| `result_json` | json | 是 | 投票统计与结果。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `updated_at` | datetime | 是 | 更新时间。 |

`member_admission` 的 `payload_json` 至少包含 `application_id`、`target_member_id`、`target_member_no`、`applicant_name`、`role_gap`、`reason`。提案通过后不会直接接纳成员，必须执行 `ProposalExecution(action_type=admit_member_application)` 后才更新 `MemberApplication`、`Member` 并授予正式成员角色。

`role_appointment` 的 `payload_json` 至少包含内部 `target_member_id`、可读 `target_member_no`、`role_id`、`assignment_type`、`resource_id`、`scope_json`、`reason`、`start_at`、`end_at`。提案通过后不会直接创建任命，必须执行 `ProposalExecution(action_type=create_role_assignment)` 后才创建 `RoleAssignment`。

## core_proposal_vote

提案投票记录。同一 `proposal_id`、`voter_member_id` 只能有一张当前票；如果 `allow_vote_change=True` 且未到 `deadline_at`，允许改票并记录 `proposal_vote_changed` 事件。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | integer pk | 是 | 内部主键。 |
| `proposal_id` | fk | 是 | 提案。 |
| `voter_member_id` | fk | 是 | 投票成员。 |
| `voter_role_assignment_id` | fk | 否 | 投票时使用的角色任命。 |
| `choice` | enum string | 是 | `yes`、`no`、`abstain`。 |
| `reason` | text | 否 | 投票理由。 |
| `voted_at` | datetime | 是 | 投票或改票时间。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `updated_at` | datetime | 是 | 更新时间。 |

约束：同一 `proposal_id`、`voter_member_id` 唯一。投票资格只看 `eligible_voters_snapshot_json`，避免表决期间角色变化导致结果漂移。

## core_proposal_execution

提案执行记录。提案通过不等于执行完成；执行结果和错误信息由本表记录。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | integer pk | 是 | 内部主键。 |
| `proposal_id` | fk | 是 | 被执行的提案。 |
| `executor_member_id` | fk | 否 | 执行人。 |
| `executor_role_assignment_id` | fk | 否 | 执行人使用的角色任命。 |
| `action_type` | enum string | 是 | `admit_member_application`、`create_role_assignment`、`revoke_role_assignment`、`create_rule`、`create_policy`、`record_statement`、`manual`。 |
| `status` | enum string | 是 | `pending`、`succeeded`、`failed`、`skipped`。 |
| `payload_json` | json | 是 | 执行载荷。 |
| `result_json` | json | 是 | 执行结果。 |
| `error_message` | text | 否 | 执行失败原因。 |
| `executed_at` | datetime | 否 | 执行时间。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `updated_at` | datetime | 是 | 更新时间。 |

第一版重点支持 `member_admission` 提案通过后的 `admit_member_application` 执行，以及 `role_appointment` 提案通过后的 `create_role_assignment` 执行，并保持幂等：同一个已执行提案不会重复创建 active `RoleAssignment`。
## core_role_permission

角色和领域权限的绑定。日常后台中，管理员主要从角色详情页理解“角色拥有哪些能力”；`Permission` 是系统判断所需的能力明细。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | integer pk | 是 | 内部主键。 |
| `role_id` | fk | 是 | 角色。 |
| `permission_id` | fk | 是 | 权限。 |
| `scope` | string | 是 | 简单作用域，默认 `global`。 |
| `constraints_json` | json | 是 | 简单约束，例如 `resource_id` 或 `resource_ids`。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `updated_at` | datetime | 是 | 更新时间。 |

约束：同一 `role_id`、`permission_id`、`scope` 唯一。

## core_system_event

统一事件账本。只追加，不作为普通可编辑日志使用；第一版通过 `core.event_ledger.append_event()` 统一分配 `seq`、计算 `payload_hash`、`prev_hash` 和 `event_hash`。

系统不再拆分“治理事件账本”“提案事件账本”“积分事件账本”“任务事件账本”“申诉事件账本”等多套哈希链。提案、投票、执行、角色任命、角色撤销、任务生命周期、申诉生命周期、资源调整、积分获得、积分扣减、积分调整、积分冲正和系统初始化等关键事实都进入同一条可校验链。业务表仍然存在：`Proposal`、`ProposalVote`、`ProposalExecution`、`RoleAssignment`、`Task`、`Dispute`、`Resource`、`LedgerEntry` 负责结构化状态、查询、校验和后台维护；`SystemEvent` 负责全局顺序、责任追溯、业务快照和篡改可发现。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | integer pk | 是 | 内部主键。 |
| `seq` | integer unique | 是 | 单调递增系统事件序号。 |
| `event_type` | enum string | 是 | `member_created`、`member_application_submitted`、`member_application_reviewed`、`partner_application_submitted`、`partner_application_reviewed`、`role_assigned`、`role_revoked`、`proposal_created`、`proposal_vote_cast`、`proposal_vote_changed`、`proposal_passed`、`proposal_failed`、`proposal_cancelled`、`proposal_executed`、`task_created`、`task_published`、`task_assigned`、`task_claimed`、`task_submitted`、`task_reviewed`、`task_closed`、`dispute_created`、`dispute_review_started`、`dispute_resolved`、`resource_adjusted`、`credit_earned`、`credit_deducted`、`credit_adjusted`、`credit_reversed`、`system_initialized`。 |
| `aggregate_type` | string | 是 | 聚合类型，例如 `RoleAssignment`。 |
| `aggregate_id` | string | 是 | 聚合记录 ID。 |
| `actor_member_id` | fk | 否 | 行为人。 |
| `actor_role_assignment_id` | fk | 否 | 行为人使用的角色任命。 |
| `payload_json` | json | 是 | 事件快照。 |
| `payload_hash` | string | 是 | `payload_json` 的规范化 SHA-256 哈希。 |
| `prev_hash` | string | 否 | 上一条系统事件的 `event_hash`。 |
| `event_hash` | string unique | 是 | 当前事件哈希。 |
| `occurred_at` | datetime | 是 | 事件发生时间。 |
| `created_at` | datetime | 是 | 记录创建时间。 |

`payload_hash` 基于稳定的 canonical JSON 计算，固定 key 顺序和分隔符。`event_hash` 由 `seq`、`event_type`、`aggregate_type`、`aggregate_id`、`actor_member_id`、`actor_role_assignment_id`、`payload_hash`、`prev_hash` 计算。`core.event_ledger.verify_event_chain()` 会按 `seq` 从第一条事件开始校验序号、`prev_hash`、`payload_hash` 和 `event_hash`。

当前 MySQL 哈希链是应用层篡改可发现机制，不是绝对不可篡改存证；它没有外部锚定，也没有数据库存储过程强制保护。Django model/admin 会阻止普通新增和修改历史事件，但数据库级写入或 ORM `update()` 仍可绕过保护，绕过后的不一致应通过 `verify_event_chain()` 被发现。错误不能通过改写历史 `SystemEvent` 修复，只能追加新的撤销、冲正或更正事件。

## 治理权限判断

`core.permission_services.member_has_permission(member, permission_code, resource=None, at_time=None)` 是当前最小权限判断入口。`at_time` 为空时使用当前时间；权限只从 `Member -> active RoleAssignment -> RolePermission` 推导，`revoked`、`suspended`、`expired` 任命不提供权限，`start_at <= at_time <= end_at` 才在时间窗口内生效。

`core.access.user_has_governance_permission(user, permission_code, resource=None, at_time=None)` 是现有治理入口函数。它根据用户关联的 `Member` 调用 `member_has_permission()`；没有绑定 `governance.*` 权限的基础角色不能进入治理入口。主权限模型是 `Member -> RoleAssignment -> RolePermission -> Permission`。

传入 `resource` 时会做简单资源匹配：`RolePermission.constraints_json.resource_id/resource_ids` 或 `scope` 为 `global`、`all`、空值可匹配。`resource=None` 表示不限定具体资源，只判断该成员在任一资源范围上是否具备该权限。

Django Admin 当前只在 control plane 暴露，并提供关系化底层维护入口：`Member` 详情页内联显示和新增 `RoleAssignment`，`Organization` 详情页内联显示 `Role`，`Role` 详情页内联显示 `RolePermission` 和拥有该角色的成员。`Proposal` 用于查看和维护通用治理提案，详情页内联显示 `ProposalVote` 和 `ProposalExecution`。固定 world 站点不暴露 `/admin/`；真实世界和仿真世界的日常用户系统不需要 `is_staff` 账号。`SystemEvent` 和 `LedgerEntry` 集中在“技术审计与配置”分组；其中 `SystemEvent` 在 Admin 中仍然只读，只用于查看事件快照和哈希链信息。

`SimulationSnapshot`, `SimulationSnapshotItem`, `SimulationRunDisposition`, and the simulation lab entrypoint live under the control-plane `/admin/` simulation group. The lab keeps only unique actions such as start, advance, run review, abort, archive, and reject. Business `Event` is not registered in Django Admin; fixed-world API and `/observer/` display it. `Ruleset` changes should go through proposals or a dedicated rule publishing flow, `CapacityAssessment` belongs to observer summaries, and `Permission` / `RolePermission` are primarily maintained through role detail screens.

## core_ruleset

规则版本记录。`Ruleset` 是 world 业务数据，不是 control DB 的全局配置；真实世界和每个仿真世界都在各自 world 数据库中保留自己的 `core_ruleset` 数据。后续规则变更应通过提案或专门规则发布流程创建新版本。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `ruleset_id` | string pk | 是 | 稳定 ID。 |
| `version` | string unique | 是 | 例如 `ruleset-v0.1.0`。 |
| `status` | enum string | 是 | `draft`、`active`、`retired`。 |
| `effective_from` | date | 是 | 开始生效日期。 |
| `effective_to` | date | 否 | 退役或失效日期。 |
| `negative_point_floor` | json | 是 | 各成员类别的积分下限。 |
| `task_point_rules` | json | 是 | 任务基础分和系数规则。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `created_by` | json | 是 | 对该规则版本负责的 ActorRef。 |
| `change_summary` | text | 是 | 规则变化说明。 |
| `metadata` | json | 是 | 扩展对象。工程类节点可在这里声明 `required_responsibility_closures` 和已取得的 `responsibility_documents`。 |

## core_project_plan

项目执行计划总表。它是主线任务线的数据库源头，不使用 Markdown 作为权威记录。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `plan_id` | string pk | 是 | 稳定计划 ID，例如 `plan-bigapple001`。 |
| `name` | string | 是 | 计划名称，例如 `bigapple001据点执行计划`。 |
| `status` | enum string | 是 | `draft`、`active`、`archived`。 |
| `description` | text | 否 | 计划说明。 |
| `target_location` | string | 否 | 目标地点。 |
| `owner` | json | 是 | 计划责任人 ActorRef。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `updated_at` | datetime | 否 | 更新时间。 |
| `metadata` | json | 是 | 扩展对象。 |

## core_plan_revision

项目执行计划版本。模拟运行后续应绑定具体版本，避免计划编辑污染历史模拟结果。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `revision_id` | string pk | 是 | 稳定版本 ID。 |
| `plan_id` | fk | 是 | 所属执行计划。 |
| `revision_code` | string | 是 | 计划内唯一版本号。 |
| `status` | enum string | 是 | `draft`、`published`、`retired`。 |
| `title` | string | 是 | 版本标题。 |
| `change_summary` | text | 是 | 变更说明。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `created_by` | json | 是 | 创建人 ActorRef。 |
| `published_at` | datetime | 否 | 发布时间。 |
| `metadata` | json | 是 | 扩展对象。 |

约束：同一 `plan_id` 下 `revision_code` 唯一。

## core_plan_node

项目执行计划节点。可表示阶段、里程碑、工程包、运营包、治理节点、招募节点、抵达节点、容量门槛和扩容节点。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `node_id` | string pk | 是 | 稳定节点 ID。 |
| `revision_id` | fk | 是 | 所属计划版本。 |
| `parent_id` | fk self | 否 | 上级节点。 |
| `sequence` | integer | 是 | 排序。 |
| `code` | string | 是 | 人类可读节点编号，例如 `B1`。 |
| `title` | string | 是 | 节点标题。 |
| `node_type` | enum string | 是 | `stage`、`milestone`、`work_package`、`operations`、`governance`、`recruitment`、`arrival`、`capacity_gate`、`expansion`。 |
| `status` | enum string | 是 | `planned`、`in_progress`、`blocked`、`completed`、`cancelled`。 |
| `is_required` | boolean | 是 | 是否必要节点。 |
| `is_expandable` | boolean | 是 | 是否可分阶段扩容。 |
| `allow_simulation_adjustment` | boolean | 是 | 是否允许模拟提出调整建议。 |
| `description` | text | 否 | 节点说明。 |
| `planned_start_day` | integer | 否 | 计划开始模拟日。 |
| `planned_duration_days` | integer | 是 | 计划工期天数。 |
| `planned_end_day` | integer | 否 | 计划完成模拟日。 |
| `estimated_cost_low` | decimal | 是 | 低估成本。 |
| `estimated_cost_expected` | decimal | 是 | 预期成本。 |
| `estimated_cost_high` | decimal | 是 | 高估成本。 |
| `required_people_min` | integer | 是 | 最低人数。 |
| `required_people_max` | integer | 是 | 建议人数。 |
| `required_person_days` | decimal | 是 | 预计人天。 |
| `required_skills` | json | 是 | 所需技能。 |
| `required_resources` | json | 是 | 所需资源。 |
| `completion_criteria` | json | 是 | 完成标准。 |
| `risk_notes` | text | 否 | 风险说明。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `updated_at` | datetime | 否 | 更新时间。 |
| `metadata` | json | 是 | 扩展对象。 |

## core_plan_dependency

计划节点依赖。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `dependency_id` | string pk | 是 | 稳定依赖 ID。 |
| `revision_id` | fk | 是 | 所属计划版本。 |
| `node_id` | fk | 是 | 后续节点。 |
| `depends_on_id` | fk | 是 | 前置节点。 |
| `dependency_type` | enum string | 是 | `finish_to_start`、`resource_gate`、`capacity_gate`、`governance_approval`、`recruitment_threshold`。 |
| `description` | text | 否 | 依赖说明。 |
| `metadata` | json | 是 | 扩展对象。 |

## core_plan_requirement

计划节点需求明细，用于记录预算、人力、技能、材料、设备、空间、许可和容量需求。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `requirement_id` | string pk | 是 | 稳定需求 ID。 |
| `node_id` | fk | 是 | 所属计划节点。 |
| `resource_id` | fk | 否 | 对应 `core_resource`。当需求可以对应库存台账中的资源时填写，用于计算缺口和匹配报价。 |
| `requirement_type` | enum string | 是 | `budget`、`labor`、`skill`、`material`、`equipment`、`space`、`permit`、`capacity`。 |
| `name` | string | 是 | 需求名称。 |
| `quantity` | decimal | 是 | 数量。 |
| `unit` | string | 否 | 单位。 |
| `unit_cost` | decimal | 是 | 单价。 |
| `total_cost_estimate` | decimal | 是 | 总成本估算。 |
| `is_must` | boolean | 是 | 是否刚性需求。 |
| `notes` | text | 否 | 说明。 |
| `metadata` | json | 是 | 扩展对象。 |

## core_plan_capacity_impact

计划节点完成后的容量影响。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `impact_id` | string pk | 是 | 稳定容量影响 ID。 |
| `node_id` | fk | 是 | 所属计划节点。 |
| `impact_type` | enum string | 是 | `member_capacity`、`bed_slots`、`canteen_meals_per_day`、`pv_mw`、`electricity_kwh_per_day`、`storage_cubic_meter`、`office_square_meter`、`recreation_square_meter`、`hospitality_rooms`。 |
| `delta` | decimal | 是 | 容量变化量。 |
| `unit` | string | 是 | 单位。 |
| `description` | text | 否 | 说明。 |
| `metadata` | json | 是 | 扩展对象。 |

## core_simulation_run

一次基于计划版本的自动模拟运行。它记录模拟的输入快照和最终状态，不直接修改计划版本。运行隔离由当前 world 数据库提供，不再通过独立的仿真世界表二次分层。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `run_id` | string pk | 是 | 稳定模拟运行 ID。 |
| `plan_revision_id` | fk | 是 | 本次模拟绑定的计划版本。 |
| `status` | enum string | 是 | `draft`、`running`、`failed`、`completed`、`paused`、`aborted`。 |
| `current_day` | integer | 是 | 当前推进到的模拟日期。 |
| `max_turns` | integer | 是 | 本次运行允许的最大推进步数。 |
| `started_at` | datetime | 是 | 开始时间。 |
| `ended_at` | datetime | 否 | 结束、失败或暂停时间。 |
| `failure_summary` | text | 否 | 最近一次阻断性失败摘要。 |
| `metadata` | json | 是 | 输入快照，例如初始预算、剩余预算、可用人数、可用技能和平均疲劳值。 |

## core_plan_node_run_state

某个计划节点在一次模拟运行中的实际状态。它不改变 `core_plan_node.status`。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `state_id` | string pk | 是 | 稳定节点运行状态 ID。 |
| `run_id` | fk | 是 | 所属模拟运行。 |
| `plan_node_id` | fk | 是 | 对应计划节点。 |
| `status` | enum string | 是 | `pending`、`running`、`blocked`、`failed`、`completed`、`skipped`。 |
| `started_day` | integer | 否 | 该节点在本次模拟中的开始日。 |
| `completed_day` | integer | 否 | 该节点在本次模拟中的完成日。 |
| `progress_percent` | decimal | 是 | 0-100 进度百分比。 |
| `actual_cost` | decimal | 是 | 本次模拟计入的实际成本。 |
| `actual_person_days` | decimal | 是 | 本次模拟计入的人天。 |
| `blocker_reason` | text | 否 | 失败或阻塞原因。 |
| `metadata` | json | 是 | 扩展对象，例如完成后剩余预算或失败类型。 |

约束：同一 `run_id` 和 `plan_node_id` 只能有一条状态。

## core_simulation_turn

自动模拟推进日志，用于观察台按文字 MUD 方式回放。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `turn_id` | string pk | 是 | 稳定推进日志 ID。 |
| `run_id` | fk | 是 | 所属模拟运行。 |
| `turn_number` | integer | 是 | 本次运行内的推进序号。 |
| `simulation_day` | integer | 是 | 该日志对应的模拟日期。 |
| `summary` | text | 是 | 人类可读摘要。 |
| `occurred_at` | datetime | 是 | 发生时间。 |
| `metadata` | json | 是 | 标题、严重程度、事件类型和相关对象。 |

约束：同一 `run_id` 下 `turn_number` 唯一。

## core_simulation_failure

自动模拟失败记录，用于说明当前计划为什么在某个节点走不通。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `failure_id` | string pk | 是 | 稳定失败 ID。 |
| `run_id` | fk | 是 | 所属模拟运行。 |
| `plan_node_id` | fk | 否 | 失败关联的计划节点。 |
| `failure_type` | enum string | 是 | `budget_unrealistic`、`labor_shortage`、`skill_shortage`、`resource_shortage`、`dependency_unmet`、`personnel_issue`、`execution_issue`、`responsibility_closure_missing`。 |
| `severity` | enum string | 是 | `warning`、`critical`。 |
| `title` | string | 是 | 失败标题。 |
| `description` | text | 是 | 失败说明。 |
| `simulation_day` | integer | 是 | 失败发生的模拟日期。 |
| `detected_at` | datetime | 是 | 发现时间。 |
| `metadata` | json | 是 | 结构化失败细节，例如缺口预算、缺失技能、未完成依赖或缺失责任闭环文件。 |

## core_plan_revision_proposal

由模拟失败生成、等待人工审核的计划修订建议。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `proposal_id` | string pk | 是 | 稳定建议 ID。 |
| `run_id` | fk | 是 | 来源模拟运行。 |
| `source_failure_id` | fk | 否 | 来源失败。 |
| `plan_revision_id` | fk | 是 | 建议基于哪个计划版本提出。 |
| `plan_node_id` | fk | 否 | 建议关联的计划节点。 |
| `proposal_type` | enum string | 是 | `adjust_budget`、`adjust_duration`、`add_dependency`、`add_node`、`reduce_admission`、`add_requirement`、`change_capacity`。 |
| `status` | enum string | 是 | `draft`、`reviewed`、`accepted`、`rejected`。 |
| `title` | string | 是 | 建议标题。 |
| `rationale` | text | 是 | 建议依据，通常来自失败说明。 |
| `suggested_changes` | json | 是 | 结构化建议变更，例如补充技能、增加前置节点、补足预算或补齐工程责任主体与责任文件。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `metadata` | json | 是 | 扩展对象。 |

重要规则：`core_plan_revision_proposal` 只是建议，不是计划变更本身。采纳建议后应生成或更新计划版本，并保留人工审核责任人。

## core_plan_change_set

由计划修订建议生成的结构化计划数据补丁。它把建议拆成一组可审核操作，但仍不直接修改当前计划版本。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `change_set_id` | string pk | 是 | 稳定变更集 ID。 |
| `run_id` | fk | 是 | 来源模拟运行。 |
| `proposal_id` | fk | 是 | 来源计划修订建议。 |
| `plan_revision_id` | fk | 是 | 被建议修改的源计划版本。 |
| `status` | enum string | 是 | `draft`、`reviewed`、`accepted`、`rejected`、`applied`。 |
| `title` | string | 是 | 变更集标题。 |
| `summary` | text | 是 | 变更集摘要。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `reviewed_at` | datetime | 否 | 审阅时间。 |
| `applied_at` | datetime | 否 | 应用时间。 |
| `applied_revision_id` | fk | 否 | 如果已经应用，指向生成并发布为下一轮基线的新计划版本。 |
| `metadata` | json | 是 | 扩展对象。 |

重要规则：`core_plan_change_set` 是计划变更草案，不是已生效计划。人工采纳后，`simulation.plan_application.apply_plan_change_set()` 会在事务中复制源 `PlanRevision` 及其 `PlanNode`、`PlanDependency`、`PlanRequirement`、`PlanCapacityImpact`，再把变更操作应用到新版本上。仿真实验后台会以 `publish=True` 调用该服务，把新版本发布为下一轮基线，并退役同一计划下旧的已发布版本。应用成功后写入 `status=applied`、`applied_at` 和 `applied_revision_id`；重复应用同一变更集必须返回已生成版本，不得再创建新版本。应用失败时事务回滚，不应留下半成品计划版本。

## core_plan_change_operation

计划变更集中的单条结构化操作，描述未来如何修改计划数据库对象。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `operation_id` | string pk | 是 | 稳定操作 ID。 |
| `change_set_id` | fk | 是 | 所属变更集。 |
| `sequence` | integer | 是 | 变更集内排序。 |
| `operation_type` | enum string | 是 | `add_node`、`update_node_field`、`add_dependency`、`add_requirement`、`add_capacity_impact`、`reduce_admission`、`add_preparation`、`note`。 |
| `target_model` | string | 是 | 目标模型名称，例如 `PlanNode`、`PlanDependency`、`PlanRequirement`。 |
| `target_id` | string | 否 | 目标记录 ID。新增操作可为空。 |
| `target_field` | string | 否 | 目标字段名。新增操作可为空。 |
| `old_value` | json | 是 | 旧值或旧状态。 |
| `new_value` | json | 是 | 建议新值或新增对象 payload。 |
| `rationale` | text | 是 | 操作依据。 |
| `is_required` | boolean | 是 | 是否为必要操作。 |
| `metadata` | json | 是 | 扩展对象。 |

约束：同一 `change_set_id` 下 `sequence` 唯一。

重要规则：操作是声明式数据 patch。创建操作不会自动写入 `core_plan_node`、`core_plan_dependency` 或 `core_plan_requirement`。当前应用服务支持 `add_node`、`add_preparation`、`add_dependency`、`add_requirement`、`add_capacity_impact`、`update_node_field`、`reduce_admission` 和 `note`；其中 `note` 只记录应用说明，`reduce_admission` 先沉淀到新版本 metadata，后续可继续结构化。

零起点仿真生成的 `add_requirement` 会在 `new_value.metadata.requirement_kind` 中区分两类启动门槛：`capability` 表示成员或合作方需要具备实际能力，例如做饭、资料整理、采购询价；`document` 表示必须取得可归档、可追责、可作为决策依据的书面文件和签署方，例如结构报告、电气并网方案、施工安全方案或验收归档资料。

## core_simulation_snapshot

仿真快照索引，保存在 control DB 中，用于长期查询某次仿真归档。原始数据不直接塞进该表，而是写入 `raw_archive_path` 指向的不可变归档包。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `snapshot_id` | string pk | 是 | 稳定快照 ID。 |
| `title` | string | 是 | 快照标题。 |
| `simulation_round` | integer | 否 | 仿真轮次。正式历史中同一 world 递增，用于表达第几轮仿真。 |
| `scenario` | string | 否 | 仿真场景，例如 `zero_start`。 |
| `purpose` | text | 否 | 本轮仿真目的。 |
| `hypothesis` | text | 否 | 本轮仿真假设。 |
| `parameter_summary` | json | 是 | 关键参数摘要。 |
| `public_title` | string | 否 | 公开档案馆标题；为空时使用内部标题或失败标题。 |
| `public_summary` | text | 否 | 公开档案馆摘要；为空时由失败类型生成。 |
| `review_conclusion` | text | 否 | 人工复盘结论。 |
| `next_run_basis` | text | 否 | 下一轮仿真的依据和应调整方向。 |
| `publication_status` | string | 是 | `public`、`internal`、`hidden`。Observer 公开档案只展示 `public`。 |
| `source_world_id` | string | 是 | 来源仿真 world。 |
| `source_world_type` | string | 是 | 来源 world 类型。 |
| `source_database_alias` | string | 是 | 实际读取的数据库 alias。测试关闭路由时可能为 `default`。 |
| `source_database_name` | string | 否 | 来源数据库名。 |
| `source_run_id` | string | 是 | 来源 `SimulationRun.run_id`。同一个 world/run 只能归档一次。 |
| `plan_revision_id` | string | 否 | 来源计划版本。 |
| `run_status` | string | 是 | 运行最终状态。 |
| `failure_type` | string | 否 | 首个失败类型，便于快速筛选。 |
| `failure_title` | string | 否 | 首个失败标题。 |
| `snapshot_schema_version` | integer | 是 | 标准化快照结构版本。 |
| `status` | string | 是 | 当前为 `archived`。 |
| `raw_archive_path` | string | 是 | 原始归档目录。 |
| `raw_archive_hash` | string | 是 | 原始 raw 文件清单的稳定哈希；逐文件内容仍由 manifest 中的 SHA-256 校验。 |
| `report_path` | string | 否 | 预渲染报告路径。 |
| `raw_table_counts` | json | 是 | 原始归档逐模型记录数。 |
| `normalized_summary` | json | 是 | 查询和展示用标准化摘要。 |
| `code_version` | string | 否 | 归档时 Git commit。 |
| `archived_at` | datetime | 是 | 归档时间。 |
| `metadata` | json | 是 | 扩展对象，例如 manifest 路径、raw 格式版本和 raw 范围。 |

## core_simulation_run_disposition

仿真运行处置记录，保存在 control DB 中。它不是 Django Admin 的通用操作日志，而是某一轮仿真能否进入历史的业务结论。所有已结束的仿真 run 在开始下一轮前必须被人工处置：要么归档为 `SimulationSnapshot`，要么明确放弃归档并写明原因。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `disposition_id` | string pk | 是 | 稳定处置记录 ID。 |
| `source_world_id` | string | 是 | 来源仿真 world。 |
| `source_world_type` | string | 是 | 来源 world 类型。 |
| `source_database_alias` | string | 是 | 来源数据库 alias。 |
| `source_database_name` | string | 否 | 来源数据库名。 |
| `source_run_id` | string | 是 | 来源 `SimulationRun.run_id`。同一个 world/run 只能有一条处置记录。 |
| `run_status` | string | 是 | run 结束状态。 |
| `run_started_at` | datetime | 否 | run 开始时间。 |
| `run_ended_at` | datetime | 否 | run 结束时间。 |
| `simulation_round` | integer | 是 | 仿真轮次；归档和放弃都会占用正式轮次。 |
| `scenario` | string | 否 | 仿真场景。 |
| `disposition` | enum string | 是 | `archived` 或 `discarded`。 |
| `reason` | text | 是 | 归档或放弃归档的原因。 |
| `decided_by` | string | 否 | 处置人或命令来源。 |
| `decided_at` | datetime | 是 | 处置时间。 |
| `snapshot_id` | fk | 否 | `archived` 时关联的 `SimulationSnapshot`。 |
| `metadata` | json | 是 | 扩展对象。 |

约束：同一 `source_world_id`、`source_run_id` 唯一。记录创建后不可通过普通 model/admin 修改。Django Admin 自带 `LogEntry` 仍记录 `/admin/` 技术操作；本表记录仿真生命周期的正式业务结论，覆盖命令行归档、命令行放弃和未来 lab 页面操作。

## core_simulation_snapshot_item

仿真快照明细索引。它不是原始全量数据，而是从原始归档和 run 关系中抽取出的可查询条目。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `item_id` | string pk | 是 | 稳定明细 ID。 |
| `snapshot_id` | fk | 是 | 所属快照。 |
| `item_type` | string | 是 | `run`、`node_state`、`turn`、`failure`、`event`、`proposal`、`change_set`、`change_operation` 等。 |
| `source_model` | string | 是 | 来源模型名。 |
| `source_pk` | string | 否 | 来源主键。 |
| `title` | string | 否 | 展示标题。 |
| `summary` | text | 否 | 摘要。 |
| `sort_order` | integer | 是 | 快照内排序。 |
| `payload_json` | json | 是 | 标准化内容。 |

## core_task

可领取、可提交、可验收的劳动任务。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `task_id` | string pk | 是 | 稳定 contract ID。 |
| `title` | string | 是 | 人类可读任务标题。 |
| `task_type` | enum string | 是 | `cooking`、`dishwashing`、`public_cleaning` 等。 |
| `status` | enum string | 是 | `draft`、`open`、`claimed`、`in_progress`、`pending_review`、`accepted`、`rejected`、`disputed`、`closed`、`reversed`。 |
| `standard_hours` | decimal | 是 | 标准工时。 |
| `base_points` | integer | 是 | 基础积分。 |
| `role_coefficient` | decimal | 是 | 规则系数。 |
| `physical_load` | decimal | 否 | 0-100 体力负担。 |
| `dirty_level` | decimal | 否 | 0-100 脏累程度。 |
| `psychological_load` | decimal | 否 | 0-100 心理负担。 |
| `urgency` | decimal | 否 | 0-100 紧急度。 |
| `can_be_delayed` | boolean | 是 | 是否允许延期。 |
| `requires_review` | boolean | 是 | 是否需要验收。 |
| `failure_consequence` | enum string | 否 | `low`、`medium`、`high`、`critical`。 |
| `assignee_member_id` | fk | 否 | 当前领取任务的成员。 |
| `plan_node_id` | fk | 否 | 该任务服务于哪个主线计划节点；为空表示临时运营任务。 |
| `source_type` | enum string | 是 | 来源类型：`direct`、`proposal`、`plan`、`simulation`、`system`。 |
| `source_proposal_id` | fk | 否 | 如果该任务由提案执行产生，关联来源提案。 |
| `source_proposal_execution_id` | fk | 否 | 如果该任务由提案执行产生，关联具体执行记录。 |
| `rule_version` | string | 是 | 创建或验收任务时使用的规则版本。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `due_at` | datetime | 否 | 截止时间。 |
| `submitted_at` | datetime | 否 | 提交时间。 |
| `reviewed_at` | datetime | 否 | 验收时间。 |
| `metadata` | json | 是 | 劳动说明、证据引用和扩展数据。 |

状态说明：

| 状态 | 含义 |
| --- | --- |
| `draft` | 运营后台已创建草稿，尚未开放给成员。 |
| `open` | 已发布，成员可以领取，运营人员也可以指派。 |
| `claimed` | 已绑定负责人，等待成员执行或提交。 |
| `in_progress` | 成员正在执行。 |
| `pending_review` | 成员已提交劳动记录，等待运营或治理成员验收。 |
| `accepted` | 验收通过，通常已经产生贡献积分流水。 |
| `rejected` | 验收驳回，需要成员重新处理或发起申诉。 |
| `disputed` | 任务进入争议流程。 |
| `closed` | 未进入成员履约链路前由运营人员关闭，不应产生积分流水。 |
| `reversed` | 历史任务被冲正或撤销，通常需要和账本冲正、事件记录配套使用。 |

任务本身不保存独立哈希字段，也不维护自己的哈希链。正式任务生命周期应通过 `core.tasks.authoring.create_task_draft()`、`publish_task()`、`assign_task()`、`close_task()`，`core.tasks.member_workflow.claim_task()`、`submit_labor()`，以及 `core.tasks.review.review_task()` 完成，并追加 `task_*` 类型 `SystemEvent`；多个 `SystemEvent` 通过 `aggregate_type = "Task"` 和 `aggregate_id = task_id` 关联同一个任务。事件 payload 会包含 `source_type`、`source_proposal_id` 和 `source_proposal_execution_id`，用于追溯任务是直接运营创建、提案执行、计划派生、仿真产生还是系统规则产生。

## core_ledger_entry

只追加的积分账本。积分余额必须从流水推导，不能直接修改余额代替流水。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `ledger_entry_id` | string pk | 是 | 稳定 contract ID。 |
| `member_id` | fk | 是 | 积分变化归属成员。 |
| `amount` | integer | 是 | 有符号积分变化。 |
| `entry_type` | enum string | 是 | `contribution`、`consumption`、`penalty`、`compensation`、`correction`、`reversal`。 |
| `reason` | text | 是 | 人类可读原因。 |
| `related_task_id` | fk | 否 | 关联任务。 |
| `related_event_id` | string | 否 | 关联事件。 |
| `rule_version` | string | 是 | 使用的规则版本。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `created_by` | json | 是 | 创建该流水的 ActorRef。 |
| `reviewer` | json | 是 | 相关验收人 ActorRef。 |
| `status` | enum string | 是 | `posted`、`pending_review`、`reversed`。 |
| `reverses_entry_id` | fk self | 否 | 被冲正或撤销的流水。 |
| `system_event_id` | fk | 否 | 对应的统一事件账本记录；新的正式服务写入应自动填充。 |
| `metadata` | json | 是 | 扩展对象。 |

重要规则：不能通过修改或删除已入账流水来修正错误。错误必须通过新的 `correction` 或 `reversal` 流水处理。正式创建流水应通过 `core.ledger_services.create_ledger_entry()`；冲正应通过 `core.ledger_services.reverse_ledger_entry()`，两者都会追加 `SystemEvent`。成员当前积分由 `posted` 流水汇总得到；如未来增加余额缓存，该缓存也必须能由流水重建。积分流水自己的 `immutable_sequence` 和 `core_ledger_sequence` 已删除，审计顺序统一使用关联的 `SystemEvent.seq`。

## core_resource

当前资源主档和库存缓存。`current_stock` 便于页面查询和预警判断；库存变化的历史事实由 `core_resource_transaction` 只追加记录，并关联统一事件账本。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `resource_id` | string pk | 是 | 稳定 ID。 |
| `name` | string | 否 | 资源名称，例如 `一号仓库`。 |
| `resource_type` | enum string | 是 | `facility`、`room`、`system`、`material`、`equipment`、`grain`、`water`、`beds` 等。 |
| `location` | string | 否 | 资源位置。 |
| `description` | text | 否 | 资源说明。 |
| `status` | enum string | 是 | `active`、`inactive`、`maintenance`、`retired`。 |
| `unit` | enum string | 是 | `kg`、`bag`、`liter`、`kwh`、`yuan`、`count`、`slot`、`cubic_meter`。 |
| `current_stock` | decimal | 是 | 当前库存。 |
| `daily_consumption_estimate` | decimal | 是 | 预计每日消耗。 |
| `replenishment_method` | enum string | 是 | `purchase`、`donation`、`production`、`reuse`、`manual_adjustment`。 |
| `loss_rate` | decimal | 是 | 0-1 损耗率。 |
| `warning_threshold` | decimal | 是 | 预警线。 |
| `shortage_impact` | json | 是 | 资源短缺对满意度、冲突、任务完成率等的影响。 |
| `updated_at` | datetime | 是 | 更新时间。 |
| `rule_version` | string | 是 | 规则版本。 |
| `metadata` | json | 是 | 扩展对象。 |

## core_supplier_quote

合作方对某一资源的供给报价。第一版直接关联 `PartnerApplication`，不单独建立完整供应商库；审核通过或备用的合作方报价可用于资源缺口匹配。它不是采购订单，也不代表已经定标或签约。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `quote_id` | string pk | 是 | 稳定报价 ID。 |
| `partner_application_id` | fk | 是 | 报价来源合作方报名。 |
| `resource_id` | fk | 是 | 可供应资源。 |
| `unit_price` | decimal | 是 | 单价。 |
| `currency` | string | 是 | 币种，默认 `CNY`。 |
| `available_quantity` | decimal | 是 | 可供数量。 |
| `minimum_order_quantity` | decimal | 是 | 最小起订量。 |
| `lead_time_days` | integer | 是 | 交付周期天数。 |
| `quality_grade` | enum string | 是 | `unknown`、`low_risk`、`standard`、`high_quality`、`risky`。 |
| `quality_summary` | text | 否 | 质量说明。 |
| `valid_from` | datetime | 否 | 有效开始。 |
| `valid_until` | datetime | 否 | 有效截止。 |
| `status` | enum string | 是 | `draft`、`active`、`expired`、`rejected`。 |
| `notes` | text | 否 | 备注。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `updated_at` | datetime | 否 | 更新时间。 |
| `metadata` | json | 是 | 扩展对象。 |

资源运营页通过 `core.resource_matching.resource_gap_rows()` 汇总已发布计划的 `PlanRequirement.resource`、当前 `Resource.current_stock` 和有效 `SupplierQuote`，展示计划需求、库存缺口、报价覆盖和最低报价。该计算只读，不创建采购单，不调整库存。

运营资源调整会写入 `metadata.last_adjustment`，当前结构为：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source` | string | 固定为 `control_resource_adjustment`。 |
| `operator` | ActorRef object | 记录操作治理成员。 |
| `reason` | string | 人类可读调整或处置原因。 |
| `delta` | string decimal | 本次库存变动数量，正数为补充，负数为扣减，`0` 为仅记录处置说明。 |
| `old_stock` | string decimal | 调整前库存。 |
| `new_stock` | string decimal | 调整后库存。 |
| `recorded_at` | datetime string | 调整记录时间。 |

## core_resource_transaction

库存流水。每次通过 `core.resource_services.record_resource_adjustment()` 调整库存时都会追加一条流水，并关联同一次 `resource_adjusted` 统一事件账本记录。该表用于回答“库存为什么变化、谁操作、变动前后是多少”；不应通过 Admin 直接新增、修改或删除历史流水。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `transaction_id` | string pk | 是 | 稳定库存流水 ID。 |
| `resource_id` | fk | 是 | 被调整资源。 |
| `transaction_type` | enum string | 是 | `inbound`、`outbound`、`stocktake_adjustment`、`loss`、`scrap`、`transfer`、`manual_adjustment`。 |
| `quantity_delta` | decimal | 是 | 库存变动数量，正数入库，负数出库或消耗，0 表示仅记录状态或处置。 |
| `stock_before` | decimal | 是 | 变动前库存。 |
| `stock_after` | decimal | 是 | 变动后库存。 |
| `reason` | text | 是 | 人类可读原因。 |
| `operator` | json | 是 | 操作人 ActorRef。 |
| `related_task_id` | fk | 否 | 关联任务。 |
| `related_supplier_quote_id` | fk | 否 | 关联供应商报价。 |
| `system_event_id` | fk | 否 | 对应统一事件账本记录。 |
| `occurred_at` | datetime | 是 | 发生时间。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `metadata` | json | 是 | 扩展对象。 |

## core_event

可回放业务事件流。该表服务于 API 和 observer，不注册到 Django Admin；它不是统一哈希账本，审计顺序和篡改检测由 `core_system_event` 负责。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `event_id` | string pk | 是 | 稳定 ID。 |
| `event_type` | enum string | 是 | `task`、`ledger`、`resource`、`dispute`、`capacity` 等。 |
| `simulation_day` | integer | 是 | 可回放的模拟日期。 |
| `simulation_run_id` | fk | 否 | 仿真生成事件所属的模拟运行；真实世界事件为空。 |
| `severity` | enum string | 是 | `info`、`warning`、`critical`。 |
| `title` | string | 是 | 短标题。 |
| `summary` | text | 是 | 公开或内部摘要。 |
| `involved_member_ids` | json array | 是 | 涉及成员业务编号列表，不强制 FK。 |
| `related_task_id` | fk | 否 | 关联任务。 |
| `related_dispute_id` | string | 否 | 关联申诉。 |
| `occurred_at` | datetime | 是 | 发生时间。 |
| `generated_by` | enum string | 是 | `live_os`、`simulation_engine`、`human_operator`。 |
| `visibility` | enum string | 是 | `public`、`internal`、`private`。 |
| `payload` | json | 是 | 结构化扩展数据。 |

约束：`generated_by = simulation_engine` 的事件必须绑定 `simulation_run_id`。`payload.run_id` 仍保留为对外事件数据的一部分，但数据库查询和隔离判断应优先使用结构化外键。

资源调整会追加两类事件：`SystemEvent(event_type = resource_adjusted, aggregate_type = Resource)` 进入统一哈希账本；`Event(event_type = resource)` 进入可回放业务事件流，用于观察台和运营页面展示。两者 payload 当前都包含：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `resource_id` | string | 被调整资源。 |
| `transaction_id` | string | 对应库存流水。 |
| `resource_type` | string | 资源类型。 |
| `unit` | string | 单位。 |
| `old_stock` | string decimal | 调整前库存。 |
| `delta` | string decimal | 变动数量。 |
| `new_stock` | string decimal | 调整后库存。 |
| `warning_threshold` | string decimal | 预警线。 |
| `is_warning` | boolean | 调整后是否仍低于或等于预警线。 |
| `replenishment_method` | string | 本次记录使用的补充方式。 |
| `reason` | string | 操作原因。 |
| `operator` | ActorRef object | 操作治理成员。 |

申诉处理会追加 `event_type = dispute` 的内部事件。其 `payload` 当前包含：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `action` | string | `start_review` 或 `resolve`。 |
| `dispute_id` | string | 关联申诉。 |
| `handler` | ActorRef object | 受理人，受理事件使用。 |
| `reviewer` | ActorRef object | 复核人，处理结论事件使用。 |
| `decision` | string | `resolved` 或 `rejected`，处理结论事件使用。 |
| `resolution` | string | 处理结论说明。 |
| `note` | string | 受理备注。 |

## core_dispute

实名申诉或复核记录。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `dispute_id` | string pk | 是 | 稳定 ID。 |
| `dispute_type` | enum string | 是 | `task_review`、`points_deduction` 等。 |
| `status` | enum string | 是 | `submitted`、`in_review`、`resolved`、`rejected`、`appealed`、`reversed`。 |
| `claimant_member_id` | fk | 是 | 实名申诉人。 |
| `respondent_member_id` | fk | 否 | 被申诉人。 |
| `related_task_id` | fk | 否 | 关联任务。 |
| `related_ledger_entry_id` | fk | 否 | 关联积分流水。 |
| `facts` | text | 是 | 事实陈述。 |
| `evidence_refs` | json array | 是 | 证据引用。 |
| `handler` | json | 是 | 处理人 ActorRef。 |
| `reviewer` | json | 是 | 复核人 ActorRef。 |
| `resolution` | text | 否 | 处理结果。 |
| `appeal_path` | string | 是 | 申诉路径。 |
| `submitted_at` | datetime | 是 | 提交时间。 |
| `resolved_at` | datetime | 否 | 解决时间。 |
| `metadata` | json | 是 | 扩展对象。 |

运营申诉处理会写入以下 `metadata` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `review_started_at` | datetime string | 申诉受理时间。 |
| `review_started_note` | string | 受理备注。 |
| `resolved_by` | ActorRef object | 记录处理结论的治理成员。 |
| `resolved_at` | datetime string | 处理结论记录时间。 |
| `decision` | string | `resolved` 或 `rejected`。 |

申诉本身不保存独立哈希字段，也不维护自己的哈希链。正式申诉生命周期应通过 `core.dispute_services.submit_dispute()`、`start_dispute_review()`、`resolve_dispute()` 完成，并追加 `dispute_*` 类型 `SystemEvent`；多个 `SystemEvent` 通过 `aggregate_type = "Dispute"` 和 `aggregate_id = dispute_id` 关联同一个申诉。

## core_capacity_assessment

容量评估结果，用于决定是否接纳新成员、扩张任务量或推进扩容计划。`CapacityAssessment` 是 world 业务数据，不是 control DB 的全局配置；真实世界和每个仿真世界都在各自 world 数据库中保留自己的 `core_capacity_assessment` 数据。observer 展示摘要；重大容量决策应通过提案或专门流程落账。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `assessment_id` | string pk | 是 | 稳定 ID。 |
| `simulation_day` | integer | 是 | 模拟日期。 |
| `current_formal_members` | integer | 是 | 当前正式成员数量。 |
| `current_candidate_members` | integer | 是 | 当前候选成员数量。 |
| `maximum_admissible_members` | integer | 是 | 当前最大可接纳人数。 |
| `recommended_new_members` | integer | 是 | 建议新增人数。 |
| `bottlenecks` | json array | 是 | 容量瓶颈列表。 |
| `risk_indicators` | json | 是 | 风险指标。 |
| `reasons` | json array | 是 | 人类可读原因。 |
| `rule_version` | string | 是 | 规则版本。 |
| `created_at` | datetime | 是 | 创建时间。 |
| `metadata` | json | 是 | 扩展对象。 |

## worlds_worldregistry

`worlds.WorldRegistry` 是 control DB 中的世界注册表，不是具体 world 的业务表。它负责把稳定的世界 ID 映射到 Django 数据库别名和物理数据库名称。

| 字段 | 说明 |
| --- | --- |
| `world_id` | 稳定世界 ID，例如 `realworld` 或 `simulation0001`；主键。 |
| `name` | 人类可读名称。 |
| `world_type` | `real` 或 `simulation`。 |
| `database_alias` | 该世界使用的 Django `DATABASES` 别名，例如 `realworld` 或 `simulation0001`。 |
| `database_name` | 独立 world 数据库的物理库名。 |
| `status` | `active`、`archived` 或 `deleted`。 |
| `archived_at` | 归档时间。 |

各 world 的业务表仍由各 app 模型拥有。世界注册表只负责路由和生命周期控制，不保存成员、任务、提案、事件等业务数据。当前默认映射是 `realworld -> realworld -> dev_big_real` 和 `simulation0001 -> simulation0001 -> dev_big_sim0001`；control 表位于 `default -> dev_big_control`。

## Database Alias Routing

Runtime database routing is request/world aware:

| App label | No world context | Fixed world request context | Migration target |
| --- | --- | --- | --- |
| `worlds` | `default` | `default` | `default` only |
| `sessions` | `default` | `default` | `default` and every world alias |
| `admin` | `default` | `default` | `default` only |
| `auth` | `default` | current world alias | `default` and every world alias |
| `contenttypes` | `default` | current world alias | `default` and every world alias |
| `core` | `realworld` by default | current world alias | every world alias only |

This means `bigadmin.local/admin/` technical accounts live in control, while `bigreal.local/...` and `bigsim.local/...` authenticate against their own world databases through root paths on their fixed-world hosts.
