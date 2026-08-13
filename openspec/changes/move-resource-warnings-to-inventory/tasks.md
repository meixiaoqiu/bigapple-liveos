## 1. 契约与资源页面

- [x] 1.1 先从 Workspace Summary schema 和 example 删除 `resource_warnings`，并通过技术契约验证
- [x] 1.2 将资源预警改为独立数据库查询并置于全部资源之前，覆盖超过资源列表上限仍不漏预警和无预警空状态

## 2. Workspace 收敛

- [x] 2.1 删除 Workspace 首页资源预警统计、列表模块及其专属 context 查询
- [x] 2.2 从 Workspace Summary 实现删除 `resource_warnings` 并更新 API 测试

## 3. 规格与文档同步

- [x] 3.1 更新 Workspace 页面测试、资源页面测试以及迁移期保留模块规格
- [x] 3.2 同步成员 Workspace、Workspace 页面和 API 产品文档

## 4. 验证

- [x] 4.1 运行定向测试、契约验证、项目检查、迁移漂移、OpenSpec strict 和两个仓库 diff 检查
- [x] 4.2 运行 Live OS 完整回归，确认资源页面、Workspace 和既有领域流程无回归
