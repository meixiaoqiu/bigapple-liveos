## 1. 技术契约

- [x] 1.1 从成员 Workspace Summary schema 的 required 与 properties 中删除 `next_actions`，并更新 example。
- [x] 1.2 运行项目既有技术契约验证，确认示例仍符合 schema。

## 2. 模块与服务器端删除

- [x] 2.1 删除 Workspace 首页完整的“下一步动作”HTML 模块。
- [x] 2.2 删除动作标签、派生函数和页面 context 键，同时保留共享的任务、申诉和资源预警数据。
- [x] 2.3 从 Workspace Summary API payload 删除 `next_actions`，并确认仓库内无剩余运行时代码引用。

## 3. 测试与文档

- [x] 3.1 更新页面和 API 测试，以否定断言验证模块及字段不存在，并验证来源领域数据仍保留。
- [x] 3.2 更新 Workspace 产品文档与旧模块迁移说明，不再宣称“下一步动作”存在。

## 4. 验证

- [x] 4.1 运行 Workspace 与 Workspace Summary API 相关测试。
- [x] 4.2 运行 Django 基础检查、迁移漂移检查、OpenSpec 严格验证、项目检查和两个仓库的 diff 检查。
