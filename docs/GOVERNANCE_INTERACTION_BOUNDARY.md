# 治理交互模型边界

本文用于约束任务、申诉、角色任命、提案、积分流水和统一事件账本之间的关系，避免把所有交互都塞进一个万能模型。

## 核心原则

系统分三层：

```text
业务对象：Task / Dispute / RoleAssignment / LedgerEntry / Resource ...
决策机制：Proposal / ProposalVote / ProposalExecution
事实留痕：SystemEvent
```

规则：

1. 具体业务保留具体模型。
2. 需要共同决定、投票或授权时，才使用提案。
3. 已经发生的关键状态变化写入统一事件账本。
4. 事件账本不替代业务表，提案也不替代业务表。
5. 错误不能通过修改历史事件解决，只能通过新的撤销、冲正、更正或后续业务动作解决。

## 业务对象不是提案

任务、申诉、角色任命、积分流水都可以和提案有关，但它们本身不是提案。

| 对象 | 它回答的问题 | 是否等同于提案 |
| --- | --- | --- |
| `Task` | 谁要做什么工作，当前做到哪一步。 | 否。任务可以由运营人员直接发布，也可以由提案批准后发布。 |
| `Dispute` | 谁对什么事实或处理结果提出争议，处理进展如何。 | 否。普通申诉不需要提案；重大裁决可以升级为提案。 |
| `RoleAssignment` | 某成员在什么时间范围内拥有哪个角色。 | 否。任命可以由上级直接创建，也可以由提案执行产生。 |
| `LedgerEntry` | 成员积分为什么增加、扣减、调整或冲正。 | 否。积分流水是账务事实；提案只可能是其来源之一。 |
| `Resource` | 当前资源库存、预警线和补充方式是什么。 | 否。资源调整是业务状态变化；重大资源政策或高影响分配才需要提案。 |
| `Proposal` | 是否批准某个待决事项。 | 是决策机制，不是所有业务对象的父类。 |
| `SystemEvent` | 谁在什么时候以什么身份对什么对象做了什么。 | 是事实账本，不承载业务状态机。 |

## 现有对象边界

### 任务

`Task` 是可领取、可提交、可验收的工作订单。它负责任务标题、类型、状态、负责人、提交说明、验收时间、计划节点和规则版本。

任务状态变化应通过 `core.tasks.*` 服务完成：

- `core.tasks.authoring.create_task_draft()`
- `core.tasks.authoring.publish_task()`
- `core.tasks.authoring.assign_task()`
- `core.tasks.authoring.close_task()`
- `core.tasks.member_workflow.claim_task()`
- `core.tasks.member_workflow.submit_labor()`
- `core.tasks.review.review_task()`

这些服务成功后追加 `task_*` 类型 `SystemEvent`。验收通过还会创建 `LedgerEntry`，积分流水再追加自己的 `credit_*` 类型 `SystemEvent`。

任务可以由提案批准后产生或发布，但任务本身仍是 `Task`。`Task.source_type`、`source_proposal` 和 `source_proposal_execution` 用于记录任务是直接运营创建、提案执行、计划派生、仿真产生还是系统规则产生；这些字段只表达来源，不替代任务状态机。

### 申诉

`Dispute` 是实名争议流程。它负责申诉人、关联任务、关联积分流水、事实、证据、受理人、复核人、结论和状态。

申诉状态变化应通过 `core.dispute_services` 完成：

- `submit_dispute()`
- `start_dispute_review()`
- `resolve_dispute()`

这些服务成功后追加 `dispute_*` 类型 `SystemEvent`。运营侧还会生成内部 `Event`，用于观察和业务事件流展示。

普通申诉不需要提案。只有当申诉结论需要多人共同裁决、影响成员资格、重大积分冲正、资源分配或规则解释时，才应创建相关提案。

### 资源

`Resource` 是当前资源状态。日常库存调整、预警处置和补充方式变更仍落在 `Resource` 上，不创建新的提案对象。

资源状态变化应通过 `core.resource_services.record_resource_adjustment()` 完成。服务成功后会追加 `resource_adjusted` 类型 `SystemEvent`，同时追加面向观察流的 `resource` 类型 `Event`。

### 角色任命

`RoleAssignment` 是成员权限来源。它负责成员、角色、状态、开始时间、结束时间、任命人和卸任处理人。

角色任命可以来自：

- 直接任命：上级或治理管理员通过服务直接创建。
- 提案执行：`role_appointment` 提案通过后执行，创建 `RoleAssignment`。
- 初始化：bootstrap 或治理权限初始化命令创建基础任命。

`RoleAssignment.source_type`、`source_proposal` 和 `source_proposal_execution` 用于记录任命来源。直接任命、提案执行和初始化最终都会落到同一张 `RoleAssignment` 表，避免保留多套平行任命结构。

无论来源是什么，最终权限判断仍走：

```text
Member -> active RoleAssignment -> RolePermission -> Permission
```

### 提案

`Proposal` 只处理“是否批准某件事”。它负责提案内容、表决范围、投票资格快照、通过比例、最低参与人数、截止时间和执行结果。

投票资格快照只包含能登录 workspace 的成员：成员必须满足角色/组织/全员范围规则，并且绑定 active Django `User`，或存在 active `User.username == Member.member_no` 的兼容登录账号。没有登录账号的系统主体、历史主体或仿真主体不能进入人工投票快照。

通过比例按严格超过阈值计算。`pass_ratio=50` 表示赞成票必须超过半数，而不是达到一半；因此 1 人需 1 票、2 人需 2 票、3 人需 2 票、4 人需 3 票。

当前重点支持：

```text
member_admission Proposal -> ProposalVote -> ProposalExecution -> MemberApplication + Member + RoleAssignment
role_appointment Proposal -> ProposalVote -> ProposalExecution -> RoleAssignment
```

成员报名提交自动创建最小权限 `Member`、`MemberApplication` 和 `member_admission` 提案，提案直接进入 VOTING 状态。治理成员不执行单独审核标记，也不手动发起准入提案——“成员报名审核”只是准入提案工作台。成员准入是 `yes`/`no` 二元表决：赞成票超过投票资格快照半数时立即通过，反对票超过半数时立即未通过并自动拒绝报名；未形成多数前保持表决中，截止仍未通过则失败。正式接纳只能由 `execute_proposal` 经 `admit_member_application_from_proposal` 完成，执行结果落到报名、成员状态和正式成员角色任命上，不新建平行投票表。拒绝/未通过来自提案投票结果或提案生命周期，而不是单人后台审核 action。

治理成员可在 `/workspace/applications/` 进入成员报名审核模块，查看报名资料、准入提案、投票和执行已通过提案。该模块只复用上述既有服务与表，不引入平行审核表或投票表。模块入口与所有动作 URL 都要求治理权限（`governance.view_admin`），且必须绑定 `Member` 身份；未绑定 `Member` 的 Django staff/superuser 不能绕过成员身份要求。成员准入投票只允许 `yes`/`no`，不提供弃权；反对票必须填写理由。


未来规则、政策、预算、项目计划、重大申诉裁决和重大任务发布可以使用同一套提案流程，但执行后仍应落到具体业务对象。

### 统一事件账本

`SystemEvent` 是全系统统一的只追加事件账本。它负责全局顺序、行为人、行为角色身份、聚合对象、业务快照和哈希链。

它不负责：

- 任务状态机。
- 申诉状态机。
- 提案投票规则。
- 角色权限判断。
- 积分余额计算。

这些逻辑仍在各自业务模型和领域服务中。

## 新功能开发规则

新增会改变权威状态的功能时，按下面顺序设计：

1. 先确认具体业务对象是什么。
2. 再判断是否需要提案批准。
3. 状态变化必须放进领域服务，不要让 view、admin 或 command 直接改关键字段。
4. 服务成功后追加 `SystemEvent`。
5. 失败校验必须发生在业务写入和事件写入之前。
6. 测试至少覆盖成功动作写事件、失败动作不写事件。

常见判断：

- 只是成员提交事实：通常是业务对象，不是提案。
- 只是运营人员处理日常流程：通常是业务服务，不是提案。
- 涉及多人共同授权、重大裁决、规则变化、预算或高影响资源分配：使用提案。
- 涉及追责、权益、资源数量、权限关系或账务变化：写入统一事件账本。
