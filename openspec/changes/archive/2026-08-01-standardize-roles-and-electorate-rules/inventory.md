# 现状替换清单

## Live OS 权威实现

- `core/role_catalog.py`、`core/member_roles.py`、`core/role_assignment_services.py`：直接角色名称、稳定代码、资格前置条件和派生参与状态。
- `core/models/proposals.py`、`core/proposals/voters.py`、`core/proposals/lifecycle.py`、`core/authorization_services.py`：写死的普通与专业选民政策、快照和当前资格重检。
- `core/openfga.py`、`core/management/commands/openfga_*.py`：旧 OpenFGA relation、proposal 投票授权和 tuple 重建。
- `core/identity_display.py`、Admin、workspace 与 observer 模板：旧中文角色名称和身份分组。
- `live_os/demo_seed/`、simulation 与 world 初始化命令：旧角色和提案仿真基线。
- `core/tests/`、`workspace/tests/`、`observer/tests/`、`live_os/api/tests/`：旧常量、测试夹具、选民政策和展示断言。
- `scripts/check_role_usage.py` 与项目检查：旧角色用途审计目录和允许位置。

## Technical contracts

- `static/technical-contracts/examples/member*.json`：成员和工作台示例直接暴露旧中文角色名称。
- `static/technical-contracts/schemas/capacity-assessment.schema.json` 及示例：使用旧成员分类字段。
- `static/technical-contracts/openapi/live-os.v0.1.openapi.json`：观察台摘要使用旧成员分类字段。
- 当前没有公开 Proposal 创建或投票 schema；新增规则模型暂不形成新的公开 API，若实施时新增端点或 payload，必须先补充契约。

## 正式文档

- 架构：`docs/architecture/overview.md`、`governance-boundary.md`、`database-schema.md`。
- 产品和项目：`docs/product/`、`docs/project/`、`docs/product-pages/` 中的成员、工作台、Admin、仿真和角色说明。
- 开发：`docs/development/ai-guide.md`、`role-permission-acceptance.md`、setup 与页面清单。
- 术语与运行边界：`docs/terminology/`、`docs/operations/runtime-boundary.md`。

## 替换原则

- 贡献者 / Contributor：派生状态，不创建 Role、RoleAssignment 或 OpenFGA tuple。
- 守约者 / Covenanter：成员资格，可直接记录，可作为选民选择条件。
- 典守者 / Maintainer：典守职责，可直接记录，可作为选民选择条件，不自动获得执衡投票权。
- 执衡者 / Deliberator：一年期执衡职责，可直接记录，可作为选民选择条件。
- 旧名称、旧稳定代码、旧 relation 和旧提案政策只允许保留在 OpenSpec 过程文档。
