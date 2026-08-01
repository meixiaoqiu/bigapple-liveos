## 1. 现状盘点与契约前置

- [x] 1.1 盘点 Live OS、OpenFGA 模型、仿真基线、测试和两个仓库文档中的旧角色名称、选民政策字段及专用投票分支，形成可核对的替换清单。
- [x] 1.2 检查 `../bigapple-docs/static/technical-contracts/` 中与提案、选民规则、成员身份和权限相关的契约；若 schema 或 payload 发生变化，先更新契约及其示例和校验测试。
- [x] 1.3 为 Contributor、Covenanter、Maintainer、Deliberator 建立唯一权威命名目录，明确中文正式名称、英文语义、稳定代码、所属维度、是否可直接授予及是否可用于选民选择。

## 2. 正式命名与权威事实迁移

- [x] 2.1 将 Django 角色目录、常量、服务函数、管理命令和语义变量迁移到 `Covenanter`、`Maintainer`、`Deliberator` 新基线，并保持 Contributor 仅由注册成员状态和有效 Covenanter 资格派生。
- [x] 2.2 将 OpenFGA relation、模型生成与 tuple 投影迁移到新英文语义，确保不写入 Contributor tuple，也不通过上级职责伪造其他身份或投票资格。
- [x] 2.3 创建数据库迁移和迁移前置检查：存在旧规范角色或旧提案选民数据时失败关闭并提示重置，不保留旧名称别名、旧 relation 或自动猜测转换路径。
- [x] 2.4 更新 simulation world 初始化、重置和演示数据，使重建后只包含新角色名称、新 OpenFGA relation 和新选民规则基线，且不得自动清理 real world。
- [x] 2.5 增加全仓旧制度名称审计，确保旧名称只允许存在于 OpenSpec 过程文档，不出现在运行代码、产品界面、数据库基线、测试夹具或正式项目文档中。

## 3. 可配置选民规则数据模型

- [x] 3.1 新增带稳定 code、中文名称、状态和版本的选民规则模板模型，以及不可变的版本化结构化条件定义。
- [x] 3.2 修改提案模型，使可表决提案保存规则模板版本引用和规范化条件快照，并移除 `general_deliberation`、`professional_deliberation` 等写死政策字段。
- [x] 3.3 建立提案类型与允许规则模板的显式关联，并支持不可删除的最低必要条件，确保发起人不能提交原始条件树或任意缩小选民范围。
- [x] 3.4 为规则模板、版本、提案类型约束和提案快照补充 Admin 管理边界、字段说明、不可变约束与可审计输出。

## 4. 通用规则验证与计算

- [x] 4.1 实现封闭的选择器注册表，首批支持 `registered_member`、`derived_status`、`catalog_role`、`professional_qualification`，并统一校验选择器类型、对象引用和 world 范围。
- [x] 4.2 实现仅支持 `ALL`、`ANY`、`NOT` 的结构化条件验证器，拒绝原始查询、可执行代码、未知操作符、未知选择器、跨 world 引用和无效对象。
- [x] 4.3 实现基于 QuerySet 或成员 ID 集合的通用规则计算器，避免逐成员查询，并对相同规范化输入产生稳定结果。
- [x] 4.4 实现提案创建和开始表决时的规则校验、模板版本固定与选民快照生成；缺失、禁用或不可计算的规则必须失败关闭。
- [x] 4.5 实现投票时的双重检查：成员必须位于固定快照中，且当前仍满足同一规则；快照不得成为资格失效后的授权旁路。

## 5. 首批制度规则模板

- [x] 5.1 初始化“社区共议”模板，使有效注册成员中的 Contributor、Covenanter、Maintainer 或 Deliberator 可按制度参与，并验证 Contributor 不需要额外 Role、RoleAssignment 或 OpenFGA tuple。
- [x] 5.2 初始化“守约事务”模板，要求当前有效 Covenanter 资格与当前有效 Deliberator 任期同时成立。
- [x] 5.3 初始化“专业事务”模板，在守约事务条件上增加一个明确专业领域的当前有效资格，并拒绝以其他领域资格替代。
- [x] 5.4 初始化“典守事务”模板，只用于制度明确允许由当前有效 Maintainer 决定的操作性事项，且 Maintainer 不自动获得 Deliberator 投票权。
- [x] 5.5 为每类提案配置允许的规则模板和最低必要条件，并覆盖企图以社区共议放宽专业事项、临时私有规则或只选择支持者等操纵路径。

## 6. OpenFGA 与统一授权边界

- [x] 6.1 调整 OpenFGA 模型，使其对具体 proposal 暴露通用 `can_vote` 能力，不为每个规则模板、角色或专业领域新增专用 `can_vote_*` relation。
- [x] 6.2 将 Django 规则计算结果以最小必要关系投影到对应 world 和 proposal，并保证重复 rebuild 稳定、无重复、无跨 world 泄漏。
- [x] 6.3 修改统一授权服务和投票入口，使其同时验证 Django 当前规则与具体 proposal 的 OpenFGA `can_vote`，任一侧异常、缺失或不一致均失败关闭。
- [x] 6.4 更新 OpenFGA bootstrap、探针、重建和启动检查，输出新模型与 tuple 基线所需的明确配置和诊断信息。

## 7. 产品界面与中英文表达

- [x] 7.1 将中文页面、表单、管理界面、审计输出和错误信息统一为“贡献者、守约者、典守者、执衡者”，移除旧制度标签。
- [x] 7.2 将英文页面、翻译资源和代码语义统一为 Contributor、Covenanter、Maintainer、Deliberator，并检查不存在旧英文运行时别名。
- [x] 7.3 更新成员列表与详情展示：Contributor 为派生状态，Covenanter 为成员资格，Deliberator 与 Maintainer 为独立职责，专业资格单独分组，技术后台状态不得伪装成业务身份。
- [x] 7.4 更新提案创建和详情界面，使发起人只能选择提案类型允许的规则模板及开放参数，并能查看中文规则摘要、模板版本和实际选民快照依据。

## 8. 自动化验证

- [x] 8.1 为命名目录、派生 Contributor 状态、角色授予前置条件、任期与资格失效、旧名称禁用编写单元和回归测试。
- [x] 8.2 为条件树验证、四类选择器、`ALL`、`ANY`、`NOT`、规则版本不可变、提案类型约束和失败关闭路径编写测试。
- [x] 8.3 为社区共议、守约事务、专业事务和典守事务建立角色与资格矩阵，覆盖 Contributor 参与、Maintainer 无 Deliberator 投票权、专业领域隔离及停用成员。
- [x] 8.4 为快照固定、表决期间资格撤销、新资格后获得、重复投票、门槛计算和审计事实编写提案生命周期测试。
- [x] 8.5 为 OpenFGA tuple 投影、具体 proposal 的 `can_vote`、重复 rebuild、模型异常失败关闭和 real/simulation world 隔离编写集成测试。
- [x] 8.6 运行相关最小测试、Django system check、迁移漂移检查、角色用途审计、`scripts/check_project.py`、完整本地回归和 `git diff --check`，记录每项 PASS、FAIL 或 SKIP 及原因。

## 9. 文档同步与变更验收

- [x] 9.1 按 AI 开发指南同步 `bigapple-docs` 中产品角色、治理边界、架构总览、数据库结构、Admin、仿真、提案流程和开发指南，中文正式名称与英文语义保持唯一映射。
- [x] 9.2 更新角色权限验收矩阵和提案选民规则矩阵，使每项规则指向真实存在的自动化测试、命令或人工验收证据。
- [x] 9.3 构建中英文文档站点并校验 technical contract 示例，确认旧制度名称只保留于 OpenSpec 过程文档。
- [x] 9.4 对照 proposal、design 和全部 delta spec 独立核查实现完整性，严格验证本变更；修正所有遗漏后再同步主规格并归档。
