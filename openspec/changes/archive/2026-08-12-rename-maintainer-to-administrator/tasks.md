## 1. 现状盘点与命名目录

- [x] 1.1 盘点 Live OS、OpenFGA、测试、主规格、环境变量和 Docs 中全部“典守者 / Maintainer / maintainer”使用位置并分类历史例外。
- [x] 1.2 将规范角色目录改为管理员 / Administrator / administrator，并增加旧称谓静态审计。

## 2. 运行时与数据迁移

- [x] 2.1 重命名角色常量、服务函数、命令、语义变量和管理能力辅助函数，保持具体权限 code 不变。
- [x] 2.2 将 OpenFGA 模型、tuple 投影、探针和选民规则模板迁移到 administrator 与管理事务语义。
- [x] 2.3 新增未上线数据迁移：simulation 清理旧角色事实，real/control 失败关闭，不保留运行时别名。
- [x] 2.4 更新仿真 bootstrap、角色权限基线和 `.env.example`；启动检查应能识别并报告旧环境变量。

## 3. 产品界面与测试

- [x] 3.1 将中文页面、错误信息、Admin、审计输出统一为“管理员”，英文语义统一为 Administrator。
- [x] 3.2 更新测试、夹具和角色用途目录，并覆盖管理员无执衡投票权、OpenFGA 投影和旧称谓禁用。

## 4. 规格与公开文档

- [x] 4.1 同步四份主规格，将正式含义统一为管理员 / Administrator 和管理事务。
- [x] 4.2 同步 sibling Docs 的架构、产品、开发、仿真、环境配置和术语文件，并确保正式文档不再出现典守者 / Maintainer。

## 5. 验证

- [x] 5.1 运行 OpenSpec 严格校验、旧称谓审计、角色用途审计、项目检查、Django check、迁移漂移检查和定向测试。
- [x] 5.2 按可用隔离测试环境运行完整回归、Docs 中英文构建和 `git diff --check`，记录未运行项及原因。
- [x] 5.3 对照 proposal、design 和 delta specs 完成终审，同步主规格并归档变更。
