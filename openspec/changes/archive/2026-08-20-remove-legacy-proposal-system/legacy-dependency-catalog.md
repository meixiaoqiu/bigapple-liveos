# 旧提案系统依赖目录

本目录冻结删除边界。它记录制度语义，但不允许任何条目成为运行时兼容依据。

## 旧系统专属内容

| 类别 | 标识或位置 | 处理 |
| --- | --- | --- |
| 权威模型 | `Proposal`、`ProposalVote`、`ProposalExecution` | 删除模型、导出、Admin、查询和测试 |
| 选民规则模型 | `ElectorateRuleTemplate`、`ElectorateRuleVersion`、`ProposalTypeElectorateRule` | 删除旧实现；制度要求转入迁移缺口 |
| 领域模块 | `core.proposals`、`core.electorate_rules` | 整包删除，不保留兼容门面 |
| 成员报名关联 | `MemberApplication.admission_proposal` | 删除字段；报名资料保留，集体决策失败关闭 |
| 来源关联 | `source_proposal`、`source_proposal_execution` | 从角色、凭证、任务及服务参数删除 |
| 数据库结构 | `core_proposal`、`core_proposalvote`、`core_proposalexecution` 及旧选民规则表 | 从干净迁移基线删除 |
| 用户入口 | 旧提案详情、投票、执行 URL 与模板分支 | 删除；未迁移业务显示统一关闭状态 |
| 后台与命令 | `core.admin_proposals`、`repair_member_admission_proposals` | 删除注册、命令和专属测试 |
| 事件与观察 | 旧提案事件 payload、观察台提案卡片和统计 | 删除旧投影；不伪造替代事件 |
| OpenFGA | 仅服务旧提案选民、投票或执行的 relation 与 tuple | 删除，同时保持其他授权失败关闭 |
| 仿真与演示 | 直接创建、推进、归档或执行旧提案的逻辑 | 删除；触发未迁移决策时明确停止 |
| 测试 | 仅证明旧模型、旧投票或旧执行的测试 | 删除，替换为失败关闭和残余扫描测试 |
| 公开文档与契约 | 描述上述模型、字段、端点或 payload 的有效说明 | 删除或标记对应流程当前关闭 |

## 必须由统一提案系统承接的制度语义

- 成员准入、角色任命与卸任、财务职责任命的发起资格、选民、阈值、截止、执行和审计。
- 社区共议、守约事务、专业事务、管理事务的可配置参与范围。
- 专业资格限制、任期限制、缺席责任、反对或拒绝结果及实名责任记录。
- 选民规则版本冻结、资格快照、投票唯一性、截止后不可投票和幂等执行。
- 仿真中的提案生命周期与真实 world 隔离。

这些语义不是本次删除目标；详细恢复条件见 `unified-proposal-migration-gaps.md`。

## 新系统同名概念

以下内容不是旧系统残余，不得因名称含有 `Proposal` 而误删：

- `ApprovalProposal`、`ApprovalDecision`：统一审批提案的当前基础模型。
- `PlanRevisionProposal`、`PlanChangeSet`、`PlanChangeOperation`：仿真计划修订建议，不是旧治理提案。
- `core.proposal_services`：新审批提案领域服务；需要按模型语义判断，不能仅凭模块名删除。
- 产品和 OpenSpec 中描述未来统一提案制度的中文“提案”一词。

## 过程历史例外

旧标识只允许出现在本 OpenSpec 变更、Git 历史和残余检查器自身的禁止目录中。产品源码、模板、迁移、测试、Docs 和 technical contracts 最终必须清零。
