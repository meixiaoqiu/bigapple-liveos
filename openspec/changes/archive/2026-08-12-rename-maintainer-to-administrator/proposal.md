## Why

产品已经决定将原“典守者 / Maintainer”正式改名为“管理员 / Administrator”。当前运行时代码、OpenFGA、界面、测试、环境变量和文档仍混用旧称谓，导致用户看到的身份与正式制度语言不一致。

## What Changes

- **BREAKING**：将角色中文正式名称从“典守者”改为“管理员”，英文代码语义从 `Maintainer` 改为 `Administrator`。
- 将稳定角色代码、常量、函数、命令、环境变量、OpenFGA relation、测试夹具和审计目录统一迁移到 `administrator` 语义，不保留 `maintainer` 运行时别名。
- 将“典守事务”统一改为“管理事务”，保持管理员不自动取得执衡者任期或其他投票权的制度边界。
- 同步 Live OS 主规格、OpenSpec 变更记录以外的正式内容和 sibling Docs；增加旧称谓审计，确保“典守者”及角色语义 `Maintainer` 永不重新进入正式代码和文档。
- 未上线阶段不兼容旧角色数据；simulation world 可重建，real/control 发现旧管理员角色事实时失败关闭。

### 非目标

- 不改变管理员现有权限集合、任命条件或授权范围。
- 不让管理员自动成为执衡者，不改变守约事务、专业事务和社区共议的选民规则。
- 不为任何具体个人建立管理员特例。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `role-authority-facts`：正式角色唯一映射改为管理员 / Administrator，旧典守者语义不得作为运行时别名保留。
- `role-presentation`：所有中文界面显示管理员，英文翻译和代码语义使用 Administrator。
- `openfga-authorization-policy`：直接关系与管理能力统一使用 administrator 语义，权限边界保持不变。
- `configurable-electorate-rules`：原典守事务模板改名为管理事务模板，仍只选择当前有效管理员。

## Impact

- 代码：角色目录、任命服务、授权服务、OpenFGA 模型、管理命令、仿真基线、环境变量和测试。
- 数据：新增迁移拒绝旧规范角色数据；不转换或保留旧名称。
- 权限：能力集合不变，仅更换规范角色与 relation 名称；管理员仍不自动获得执衡投票权。
- 公开契约：不改变 API payload 结构；角色显示值和文档术语发生破坏性变更。
- 文档：同步 `bigapple-docs` 的架构、产品、开发、仿真和术语说明。
