# 验证记录

## 自动验证

- 旧提案残余与角色用途项目检查：PASS。
- Django system check：PASS。
- 迁移漂移检查：PASS。
- OpenFGA JSON 解析：PASS；FGA 与 JSON 均不再定义旧提案关系。
- 定向回归：81 项旧提案删除与观察者/工作台测试 PASS；56 项报名与执衡者考试测试 PASS；28 项工作台页面测试 PASS。
- 完整隔离回归：1180/1180 项 PASS，1 项按既有条件 SKIP；测试数据库覆盖 default、realworld、simulation0001。
- Docs 中文与英文构建：PASS。
- OpenSpec strict：PASS。

## 人工验收

- 2026-08-16 已完成 real 与 simulation 验收：real 匿名工作台和 simulation 管理员报名审核页均显示统一提案迁移期关闭说明；两端浏览器控制台无错误，请求返回 200。
- real 与 simulation 分别调用成员准入提案创建服务，均抛出 `ProposalFlowUnavailable`；报名、审批提案、审批决定、角色任命和系统事件等权威表计数在调用前后保持一致。
- 两端最近服务日志未发现旧模型导入、HTTP 500 或 `Traceback`；旧提案残余扫描继续通过。
