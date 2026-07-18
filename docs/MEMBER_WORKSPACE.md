# 成员工作台

## 入口

成员工作台是固定 world 站点的唯一成员自助入口：

```text
/workspace/
```

未登录用户访问 `/workspace/` 时，展示 **workspace 入口门禁页**（`templates/workspace/login_required.html`），引导注册、登录或先去观察台，不直接返回 403。登录后才进入个人 workspace。

本地开发常用入口：

```text
http://127.0.0.1:20101/workspace/
http://127.0.0.1:20102/workspace/
```

旧 `/member/` 入口已移除，不再保留兼容路径。

## 身份来源

工作台不从 URL 选择成员，也不使用 `/members/{member_no}/workspace/` 这类入口。当前成员必须从登录账号绑定关系推导：

```text
User -> Member
```

如果当前登录账号没有绑定目标 world 中的 `Member`，访问 `/workspace/` 会被拒绝。

## 长期架构：所有注册用户都拥有最小 workspace

当前 workspace 入口只对已绑定 Member 的登录用户开放，正式成员和报名审核中的申请人看到的页面不同。长期架构下，**所有注册用户都拥有最小 workspace**，其设计原则如下：

1. **注册即获 workspace。** 通过 `/register/` 注册并绑定 Member 的用户，无论是否通过正式成员审核，都可访问 `/workspace/`。最小 workspace 不依赖正式成员身份。`/workspace/apply/` 是登录后的正式成员报名入口，不会创建账号。

2. **最小 workspace 至少包含：**
   - 公开资料维护（`/workspace/profile/`）：编辑公开姓名、头像 URL，展示在 Observer 公开主页。
   - 正式成员报名入口：已注册但尚未成为正式成员的用户，可在 workspace 内发起正式成员报名申请。
   - 基础身份信息展示：当前角色、Credential 列表、近期活动摘要。

3. **正式成员通过角色获得更多功能。** 正式成员只是获得了 `full_member` 角色。该角色在 RoleAssignment 中拥有更多 RolePermission，workspace 根据角色动态展示对应功能模块（任务、申诉、治理审核等）。功能扩展来自 RoleAssignment 的变化，不是"切换 workspace 版本"。

   **当前落地**：完整 workspace 主授权看 active `ROLE_FORMAL_MEMBER`（`member_has_role(member, ROLE_FORMAL_MEMBER)`）。`SUSPENDED` / `EXITED` 作为生命周期禁用状态行使 veto——即使有 `ROLE_FORMAL_MEMBER`，禁用状态成员也不能进入完整 workspace。`Member.status` 只作为生命周发展示字段，不作为权限来源。

4. **正式成员编号不是登录账号，也不是权限来源。**
   - 登录仍使用 `User.username`，不因获得正式编号而创建新账号。
   - 正式成员编号（如 `#1`）是一次性发放的 Credential Grant，永不复用，退出后保留为历史归属证明。
   - 编号不参与任何权限判断。成员退出后 RoleAssignment 撤销、workspace 功能回收，编号只作为"曾经是第几号正式成员"的公开记录存在。

## 当前功能

当前最小工作台覆盖：

- 查看当前成员状态、积分和当前任务。
- 领取可领取任务。
- 提交已领取任务的劳动记录和证据引用。
- 提交申诉。
- 查看个人任务历史、近期事件、资源预警和申诉状态。
- 维护公开资料（公开姓名、头像 URL），所有注册用户（含报名审核中的申请人）可用。

## 表单入口

```text
POST /workspace/tasks/{task_id}/claim/
POST /workspace/tasks/{task_id}/submit-labor/
POST /workspace/disputes/
```

任务领取、劳动提交和申诉提交仍通过对应领域服务完成，并写入必要的业务事件和统一事件账本。

### 公开资料维护

```text
GET  /workspace/profile/
POST /workspace/profile/update/
```

当前成员（包括 pending applicant）可以维护公开姓名和头像 URL，展示在 `/u/<member_no>/` 公开主页。公开主页包含身份头部（badge + 正式成员编号 Credential）、公开凭证列表、治理身份（RoleAssignment → RolePermission，中文语义）和近期公开治理记录。不能编辑角色、权限、治理身份，不提供简介和可见性自助编辑。治理身份仍由 RoleAssignment 动态计算，不来自个人填写。

公开资料页（`/workspace/profile/`）的"我的凭证"区域展示当前成员的 Credential Grant 列表（通过 `credentials_for_member()` 获取），如正式成员编号 `#1`。凭证只读显示，用户不能编辑。凭证是公开事实/荣誉/资格证明，不是权限来源。

## 与 Control 后台的关系

`/workspace/` 是成员本人使用的工作台，不承担底层管理职责。

成员账号创建、角色任命、提案处理、任务兜底维护、资源底层调整、申诉兜底处理、仿真归档等高影响操作，统一通过 control 后台或领域服务完成。
