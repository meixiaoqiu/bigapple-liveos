## Why

执衡者考试目前依赖一次性数据迁移创建默认题目和政策；world 执行 `flush` 或重置后，迁移记录仍在而考试数据已消失，守约者只能在点击申请后看到“考试政策尚未发布”。同时，考试配置只暴露在 Django Admin 中，默认 `is_staff=False` 的业务管理员没有可靠的 workspace 配置入口，系统因此可能长期停留在无人能够恢复的半初始化状态。

## What Changes

- 复用一项最小考试可用性判断，区分考试可用、无有效政策和已发布题目不足，避免页面显示可开始而提交后才失败。
- simulation world 在重置或初始化后恢复明确标记为仿真用途的考试基线；real world 不静默发布示例考试，而是进入待管理员配置状态。
- 为具备 `governance.manage_deliberator_exam` 权限的管理员提供最小 workspace 配置入口，可以创建并发布题目、发布抽题数量和及格线，不依赖 Django `is_staff` 或 `is_superuser`。
- 普通守约者在开始考试前看到统一的“执衡者资格考试暂未开放，请稍后再试”，考试不可用时禁用开始操作。
- 保持题目答案、解释和考试快照为受控资料；公开考试政策不等于公开正确答案。
- 不改变执衡者一年任期、守约者前置资格、服务端随机组卷和服务端评分规则。

## Capabilities

### New Capabilities

- `deliberator-exam-readiness`: 定义最小考试可用性判断和 simulation 重置后的基线恢复规则。

### Modified Capabilities

- `deliberator-qualification-exam`: 增加业务管理员 workspace 配置入口、考试开始前的就绪判断及真实 world 的显式发布边界。

## Impact

- 影响 `core.deliberator_exam_services`、simulation reset、workspace 路由/视图/模板和管理权限检查。
- 需要补充 flush 后恢复、simulation reset、最小配置入口和权限矩阵测试。
- 权限影响：配置入口只接受当前有效且具有 `governance.manage_deliberator_exam` 的成员；管理员称谓本身、Django staff/superuser 标记均不能替代具体权限检查。
- 数据影响：simulation 可以幂等创建仿真基线题目与政策；real 只报告未就绪，不自动发布示例内容。既有已发布题目、政策和考试尝试不得被初始化流程覆盖或删除。
- 公开契约影响：不修改现有 API、schema 或 payload；只同步直接相关的管理员、执衡者考试和仿真重置文档。
- 非目标：不新增独立就绪检查命令、不修改 `start.bat`、不建设考试统计或完整管理中心、不设计完整教育课程、不决定真实题库内容、不允许管理员替成员手工通过考试。
