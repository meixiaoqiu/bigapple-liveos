# 当前提案依赖清单

## 权威模型

| 对象 | 当前作用 | 本变更处理 |
| --- | --- | --- |
| `ApprovalProposal` | 采购采纳、采购付款等跨业务审批的聚合根；成员准入类型存在但被服务层关闭 | 演进为唯一统一提案聚合根，增加选民策略与生命周期字段 |
| `ApprovalDecision` | 按硬编码审批槽记录采购等审批决定 | 保留给尚未迁移的审批策略；成员准入不得使用该模型模拟投票 |
| `MemberApplication` | 保存贡献者提交的守约者报名和最终状态 | 关联唯一准入提案，报名状态只能由准入适配器更新 |
| `RoleAssignment` | 保存守约者、执衡者、管理员及其他职责事实 | 准入执行必须通过角色任命服务创建一年期守约者任期 |

## 运行入口

| 入口 | 当前状态 | 本变更边界 |
| --- | --- | --- |
| `core.application_services.create_approval_proposal_for_application` | 始终抛出 `ProposalFlowUnavailable` | 改为调用成员准入适配器；政策缺失时保存等待状态 |
| `core.proposal_services` | 使用审批层级与硬编码角色组完成采购审批 | 抽取统一生命周期与适配器注册表；现有采购行为保持兼容 |
| workspace 报名列表与详情 | 只读并显示迁移关闭提示 | 增加真实提案状态、资格解释、投票和执行入口 |
| workspace 提案页 | 展示和操作现有采购审批 | 同一聚合根展示两种明确策略，不把采购审批冒充选民表决 |
| Django Admin | 报名只读，提案存在维护入口 | 新规则、票据、状态与执行记录保持只读诊断 |
| observer 报名事项 | 展示报名与已有结果事件 | 增加公开安全的提案阶段与结果，不泄露报名私密字段 |
| simulation screening | 只写报名 metadata，不改变准入状态 | 保持非权威筛选；统一提案自动决策仍失败关闭 |

## 授权与 OpenFGA

- 当前治理权限由 `AuthorizationService` 和 OpenFGA 计算，角色目录包含 `governance.manage_people`、`governance.manage_roles` 等具体权限。
- 当前 OpenFGA 模型不包含旧提案 relation；成员准入失败关闭路径不写 tuple。
- 本变更新增 `governance.manage_proposal_policies`，提案发起、投票和执行继续使用具体权限与规则资格，不能用 `is_staff`、`superuser` 或角色名称旁路。

## 旧系统残余结论

- 产品运行时代码没有导入已删除的旧 `Proposal`、旧投票或旧执行模型。
- 当前名为 `ApprovalProposal` 的模型是保留的新审批聚合根，不是已删除的旧 `Proposal` 兼容门面。
- `core.proposal_migration` 只提供未迁移流程的统一失败关闭错误，不读取或写入旧结构。
- `PlanRevisionProposal` 属于仿真计划修订建议，不属于治理提案体系，名称相似但语义和数据边界独立。

