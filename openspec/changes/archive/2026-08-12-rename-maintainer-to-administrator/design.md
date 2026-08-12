## Context

见 `proposal.md`。该称谓横跨 Django 权威角色目录、OpenFGA relation、初始化命令、仿真基线、环境变量、测试和两个仓库的正式文档；当前未上线且允许重建仿真数据。

## Goals / Non-Goals

**目标：**

- 建立“管理员 / Administrator / administrator”的唯一全栈映射。
- 让旧“典守者 / Maintainer / maintainer”只存在于本次 OpenSpec 过程文档和历史迁移中。
- 保持所有现有管理权限、守约者前置条件及与执衡者职责分离的边界。

**非目标：**

- 不重设计权限集合或管理员任命流程。
- 不增加兼容别名、个人专属管理员或隐式投票权。

## Decisions

### 1. 全量语义迁移，不做显示层别名

角色稳定代码、Python 标识符、OpenFGA relation、命令和环境变量全部迁移到 administrator。仅改中文标签会让授权模型和代码继续传播旧概念，因此不采用。

### 2. 历史迁移保留，正式运行内容禁止旧名

Django 已应用迁移是 schema 历史，不能机械重写；旧 OpenSpec 归档是过程历史。项目检查忽略这些范围，并对其他代码、测试、主规格和 Docs 执行旧称谓审计。

### 3. 未上线数据失败关闭

新增迁移对 simulation world 清理旧管理员角色事实，对 real/control 发现旧角色事实时中止并要求明确重置。不创建旧名到新名的运行时兼容映射。

### 4. 管理能力代码同步改名但权限 code 保持稳定

角色语义和函数名改为 administrator；既有 `governance.*` 权限 code 是具体能力契约，不因角色称谓变化而更换，避免制造无意义的权限迁移。

## Risks / Trade-offs

- **风险：大量机械重命名遗漏调用点** → 使用全仓静态审计、角色用途审计和完整回归验证。
- **风险：本机 `.env` 仍使用旧变量名** → 启动检查明确报告旧变量，并在 `.env.example` 和 Docs 中提供新变量；本机配置需迁移。
- **风险：OpenFGA 模型 ID 变化** → 重新 bootstrap real/sim 模型并按现有人工 `.env` 流程更新模型 ID。

## Migration Plan

1. 先更新角色目录、服务和 OpenFGA 模型，再生成数据库迁移。
2. 同步仿真初始化、环境变量、命令和测试。
3. 更新主规格与 sibling Docs，并启用旧称谓审计。
4. 运行迁移检查、定向测试、完整回归、OpenFGA bootstrap 与启动验证。
