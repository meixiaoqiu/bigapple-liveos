## 1. 技术契约

- [x] 1.1 删除 dispute schema/example 和 OpenAPI `/disputes`，新增 event-feedback schema/example 与 `/event-feedbacks`
- [x] 1.2 将 Event 和 Workspace Summary 契约中的 dispute 字段替换为 feedback 字段，并通过全部技术契约验证

## 2. 数据模型与迁移

- [x] 2.1 用 `EventFeedback` 模型和明确成员/Event 外键替换 `Dispute`，并更新模型导出、Admin 与 ID 生成器
- [x] 2.2 更新 Event、SystemEvent 类型和关联字段，生成删除旧数据且不提供兼容映射的迁移
- [x] 2.3 更新 world reset、demo seed 和模型测试，确认新建环境不再产生 Dispute 数据

## 3. 领域服务与权限

- [x] 3.1 实现反馈提交、开始核实、请求回应、相关方回应、形成结论、结束和撤回 service，并为每个合法转换追加统一账本事件
- [x] 3.2 实现默认实名公开和三档提交人身份展示范围，覆盖非公开理由、第三方隐私、相关方和处理者可见性
- [x] 3.3 实现反馈 serializer/API，删除旧 dispute API、serializer 和 URL，不保留兼容别名

## 4. 事件详情与 Workspace

- [x] 4.1 在公开 Event 详情为已登录成员增加固定事件反馈表单和个人可见反馈列表，匿名访问保持只读
- [x] 4.2 增加反馈详情、相关方回应与治理核实入口，所有动作复用领域 service，公布统一结论并保持结果事件关联
- [x] 4.3 将“我的事务”切换为反馈投影，并从 Workspace 首页删除申诉状态、提交表单和旧 context 查询

## 5. Observer 与其他集成

- [x] 5.1 将 Observer Dashboard、事件语义展示和关联标签改用 EventFeedback，并确保身份展示范围和第三方脱敏在公开输出中生效
- [x] 5.2 清理产品代码、测试和 seed 中旧申诉领域命名；兑换订单的问题反馈保持独立业务动作

## 6. 文档同步

- [x] 6.1 更新数据库 schema、治理边界、架构、Admin、成员 Workspace、Observer 与 API 文档
- [x] 6.2 更新聚合首页迁移清单和相关 active OpenSpec，消除 Dispute/申诉当前事实冲突

## 7. 验证

- [x] 7.1 运行模型、service、权限、API、事件详情、Workspace、Observer 和 seed 定向测试
- [x] 7.2 运行技术契约、项目检查、Django check、迁移漂移、OpenSpec strict 和两个仓库 diff 检查
- [x] 7.3 运行 Live OS 完整回归，确认旧 Dispute 接口不存在且既有事件与领域流程无回归

## 8. 终审修复

- [x] 8.1 为全部既有反馈状态转换增加事务内行锁，并增加 MySQL 并发转换测试
- [x] 8.2 将 EventFeedback Admin 改为只读查询入口，禁止绕过领域 service 修改权威事实
- [x] 8.3 限制成员提交原始内容的公开范围，并增加第三方隐私页面测试
- [x] 8.4 严格校验反馈创建 API 的完整 payload、JSON 类型、数组元素和未知字段
- [x] 8.5 按明确责任人与状态修正 Workspace 反馈事务分组和动作标签
- [x] 8.6 修正文档残留并重新运行定向、契约、OpenSpec、项目检查和完整回归
- [x] 8.7 将事件反馈并发行锁测试加入 GitHub Actions 的 MySQL 专用 job，并验证 workflow 选择器
- [x] 8.8 清理当前实现文档中的旧 Dispute、申诉生命周期、Admin 和兑换申诉动作残留，并校准 SystemEvent 枚举
- [x] 8.9 在公开反馈详情展示结论责任人，并增加匿名页面回归测试
