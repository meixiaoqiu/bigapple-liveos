## 1. 契约与实现

- [x] 1.1 先从 Workspace Summary schema 和 example 删除 `recent_events`，并通过技术契约验证
- [x] 1.2 删除 Workspace 首页“相关事件”模块及其专属 context 查询
- [x] 1.3 从 Workspace Summary 实现删除 `recent_events` 并更新 API 测试

## 2. 测试与文档

- [x] 2.1 更新 Workspace 页面测试和迁移期保留模块规格，确认公开事件入口未改动
- [x] 2.2 同步成员 Workspace、Workspace 页面和 API 文档

## 3. 验证

- [x] 3.1 运行定向测试、契约验证、项目检查、迁移漂移、OpenSpec strict 和两个仓库 diff 检查
- [x] 3.2 运行 Live OS 完整回归，确认事件领域和既有页面无回归
