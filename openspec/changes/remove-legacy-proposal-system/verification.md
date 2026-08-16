# 验证记录

## 自动验证

- 旧提案残余与角色用途项目检查：PASS。
- Django system check：PASS。
- 迁移漂移检查：PASS。
- OpenFGA JSON 解析：PASS；FGA 与 JSON 均不再定义旧提案关系。
- 定向回归：81 项旧提案删除与观察者/工作台测试 PASS；56 项报名与执衡者考试测试 PASS；28 项工作台页面测试 PASS。
- 完整隔离回归：1251 项 PASS，1 项按既有条件 SKIP；测试数据库覆盖 default、realworld、simulation0001。
- Docs 中文与英文构建：PASS。
- OpenSpec strict：PASS。

## 尚需人工验收

- 在已重置并重新启动的 real 与 simulation 页面确认报名准入和财务职责任命均显示统一迁移关闭提示。
- 确认浏览器与服务日志没有旧模型导入错误或服务器错误。
