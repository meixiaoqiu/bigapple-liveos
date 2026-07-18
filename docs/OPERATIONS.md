# 运行入口与操作边界

## 当前结论

世界站点只保留成员工作台、观察台、注册入口和 API：

```text
/workspace/
/observer/
/register/
/api/v0.1/
```

`/apply/`、`/apply/partner/` 已删除。正式成员报名是 workspace 子功能 (`/workspace/apply/`)。合作方/供应商系统后续单独设计。`/live-admin/` 已移除。真实世界和仿真世界 runtime 不暴露 `/admin/`，也不暴露独立业务后台。

## Control 后台

所有底层、危险、会造成严重后果或需要兜底维护的操作，统一进入 control 后台：

```text
bigadmin.local/admin/
bigadmin.local/admin/simulation-lab/
```

control 后台负责：

- Django Admin 技术后台和原始数据兜底维护。
- 世界注册表、仿真实验后台、仿真归档和处置记录。
- 成员、角色、角色任命、提案、任务、资源、申诉、项目计划、统一事件账本等底层模型维护。

## 世界工作台

真实世界和仿真世界使用相同运行时入口：

```text
bigreal.local/workspace/
bigreal.local/observer/
bigreal.local/register/

bigsim.local/workspace/
bigsim.local/observer/
bigsim.local/register/
```

`/workspace/apply/` 是正式成员报名入口（workspace 子功能）。`/apply/`、`/apply/partner/` 已删除。

`/workspace/` 只面向当前登录成员本人，身份来自当前 world 数据库中的 `User -> Member` 绑定。它不是底层管理后台。

## 登录跳转

world 登录成功后统一进入 `/workspace/`。即使该成员拥有治理角色，也不会在 world 站点进入独立运营后台；需要执行底层或高影响操作时，应使用 control 后台。

## 设计原因

- world runtime 保持用户使用系统的边界，不混入 Django Admin 或危险管理操作。
- control plane 独立承载最高权限和兜底维护能力。
- 真实世界和仿真世界仍复用同一套 world runtime 代码，只通过站点配置和数据库隔离区分。
