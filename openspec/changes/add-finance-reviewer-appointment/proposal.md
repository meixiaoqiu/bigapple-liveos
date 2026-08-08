## Why

新账号完成守约者准入后仍没有可操作的路径取得财务审核职责，导致仿真世界中的报销永久停留在待审核状态。现在需要把既有的角色任命提案能力接入成员工作台，完成治理授权与财务流程之间缺失的一环。

## What Changes

- 为具备角色维护权限的典守者增加财务审核职责提名入口。
- 使用既有 `ROLE_APPOINTMENT` 提案、执衡者选民规则、投票和执行服务完成任命，不增加直接授权旁路。
- 只允许把财务审核者职责授予当前有效守约者，且不允许从准入流程自动授予。
- 在同一工作台页面展示待表决、可执行及当前有效财务审核者。
- 增加完整回归：执衡者考试、成员准入、财务任命、非本人报销审核，以及 world 隔离。
- 非目标：不实现财务付款者或公开附件发布者的自助申请，不改变报销的禁止自审规则。
- 权限影响：提名和执行需要 `governance.manage_roles`；投票仍要求提案快照中的有效守约者兼执衡者。
- 数据影响：复用 `Proposal`、`ProposalVote`、`ProposalExecution` 和 `RoleAssignment`，不新增模型。
- 公开契约影响：不新增或修改公共 API、schema 或 payload。

## Capabilities

### New Capabilities

- `finance-reviewer-appointment`: 财务审核职责的提名、治理表决、执行和端到端报销解锁流程。

### Modified Capabilities

- `role-authority-facts`: 明确财务审核职责只能由角色任命提案执行产生，且守约者准入不会隐式授予。

## Impact

影响 `workspace` 的角色任命页面、既有提案服务调用、财务和 world 隔离回归，以及产品和治理边界文档。不新增依赖；技术契约不变。
