## Why

Workspace 首页“下一步动作”只把已有任务、申诉和资源数据重新概括为固定标签，信息精度低且已被“我的事务”及各领域模块覆盖。继续保留它会造成重复展示、重复服务器端组装和无实际消费者的 API 字段。

## What Changes

- 删除 Workspace 首页完整的“下一步动作”模块。
- 删除 `workspace_next_actions()`、标签映射和页面 context 中的派生字段，但保留其他模块仍使用的任务、申诉和资源查询。
- **BREAKING**：从成员 Workspace Summary API 响应中删除 `next_actions` 字段，并先同步修改技术契约 schema 与 example。
- 删除或改写只验证该模块及字段的测试，同步更新 Workspace 产品文档。

### 目标

- 消除已被更精确事务与领域视图覆盖的重复模块。
- 删除不再承担产品职责的服务器端派生逻辑与公开字段。
- 不影响“我的事务”、待处理事项、任务、申诉和资源预警模块。

### 非目标

- 不删除任务、申诉、资源预警或相关领域查询。
- 不修改任何权威模型、状态机、权限或写入流程。
- 不删除其他 Workspace 旧模块。

### 权限影响

无权限规则或授权路径变化。

### 数据影响

无数据库 schema、迁移或权威数据变化。

### 公开契约影响

成员 Workspace Summary API 不再返回必填字段 `next_actions`，属于破坏性 payload 变更；技术契约必须先于实现更新。

## Capabilities

### New Capabilities

- `workspace-next-actions-removal`: 定义删除首页下一步动作摘要和 Workspace Summary API 对应字段后的边界与保留行为。

### Modified Capabilities

无。

## Impact

- Live OS：`workspace/context.py`、`templates/workspace/index.html`、`live_os/api/members.py` 及相关测试。
- Docs：成员 Workspace Summary 技术契约、示例和 Workspace 产品说明。
- 无新增依赖、模型或迁移。
