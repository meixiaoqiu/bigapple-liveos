## Purpose

确保考试服务与申请页面使用同一项最小可用性判断，并让 simulation world 在清空或重置后恢复可测试的考试基线。

## ADDED Requirements

### Requirement: 系统必须提供统一的考试就绪状态
系统 MUST 根据当前 world 的有效考试政策、已发布题目数量及政策抽题数量计算统一可用性，并至少区分考试可用、无有效政策和已发布题目不足。申请页面和考试开始服务 MUST 使用同一判断，不得分别推测。

#### Scenario: 考试满足全部条件
- **WHEN** 当前 world 存在唯一有效政策，且已发布有效题目数不少于政策抽题数量
- **THEN** 系统报告考试可用，并允许符合成员资格的守约者开始考试

#### Scenario: 政策或题库尚未就绪
- **WHEN** 当前 world 没有有效政策，或已发布有效题目数少于政策抽题数量
- **THEN** 系统报告不可用且不创建考试尝试

### Requirement: simulation 初始化必须恢复可用的仿真考试基线
simulation world 在新建、清空后重新初始化或重置到 zero-start 时 MUST 幂等确保存在明确标记为仿真用途的已发布基线题目和有效政策。初始化不得覆盖既有非基线题目、有效政策或考试历史。

#### Scenario: 清空后的仿真 world 重新初始化
- **WHEN** 已执行过迁移但考试数据已被清空的 simulation world 被重新初始化或重置
- **THEN** 系统恢复仿真考试基线，考试就绪检查通过，重复执行不产生重复题目或政策

#### Scenario: 仿真 world 已有业务配置
- **WHEN** simulation world 已存在管理员发布的有效政策和足量题目
- **THEN** 初始化保留现有配置，不用仿真基线覆盖或降级它

### Requirement: real world 必须由管理员显式发布考试配置
real world MUST NOT 因页面访问或普通初始化而静默发布示例题目、正确答案或考试政策。缺少可用配置时，系统必须保持不可用，直到有权管理员通过 workspace 显式发布题目和政策。

#### Scenario: 新 real world 尚未配置考试
- **WHEN** real world 完成迁移和管理员初始化但没有已发布考试配置
- **THEN** 守约者看到统一的暂未开放提示且不能开始考试，管理员可以进入最小配置入口

#### Scenario: real world 已完成显式发布
- **WHEN** 有权管理员已发布足量题目和有效政策
- **THEN** 就绪状态转为可用，不需要重新迁移或重启系统
