# 成员工作台

## 入口

成员工作台是固定 world 站点的唯一成员自助入口：

```text
/workspace/
```

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

## 当前功能

当前最小工作台覆盖：

- 查看当前成员状态、积分和当前任务。
- 领取可领取任务。
- 提交已领取任务的劳动记录和证据引用。
- 提交申诉。
- 查看个人任务历史、近期事件、资源预警和申诉状态。

## 表单入口

```text
POST /workspace/tasks/{task_id}/claim/
POST /workspace/tasks/{task_id}/submit-labor/
POST /workspace/disputes/
```

任务领取、劳动提交和申诉提交仍通过对应领域服务完成，并写入必要的业务事件和统一事件账本。

## 与 Control 后台的关系

`/workspace/` 是成员本人使用的工作台，不承担底层管理职责。

成员账号创建、角色任命、提案处理、任务兜底维护、资源底层调整、申诉兜底处理、仿真归档等高影响操作，统一通过 control 后台或领域服务完成。
