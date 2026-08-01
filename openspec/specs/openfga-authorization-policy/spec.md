# openfga-authorization-policy 规格

## Purpose

定义 OpenFGA 如何从最小直接关系推导议事、专业投票和典守权限，使守约者资格、执衡者任期、专业资格、典守者职责和 world 隔离成为相互独立且失败关闭的运行时授权条件。

## Requirements

### Requirement: OpenFGA 只接收必要的直接关系
OpenFGA tuple 投影 SHALL 只写入 Django 权威数据中当前有效且策略需要的守约者资格、执衡者任期、典守者任命、专业资格、角色权限绑定和通用选民规则所需的稳定参与关系。贡献者状态、资格交集、union、intersection 或传播关系计算出的称谓和能力 MUST NOT 作为重复 tuple 写入。

#### Scenario: 投影典守者
- **WHEN** 一个守约者直接持有典守者任命但没有执衡者任期
- **THEN** tuple 投影包含守约者资格和典守者直接关系，不包含执衡者或投票资格关系

#### Scenario: 投影专业执衡资格
- **WHEN** 一个守约者同时具有有效执衡者任期和财务专业资格
- **THEN** tuple 投影分别包含守约者、执衡者和财务专业资格的直接关系，不包含“财务投票者”等合成角色

#### Scenario: 重建 tuple
- **WHEN** 对同一 world 重复执行 tuple rebuild
- **THEN** 生成的直接关系集合稳定、无重复且与 Django 当前权威事实一致

#### Scenario: 重置后的 tuple 基线
- **WHEN** 重置 simulation world 并重建 tuple
- **THEN** OpenFGA 中只存在新命名和通用选民规则所需的直接关系，不存在旧角色、旧选民政策或旧权限模型遗留 tuple

### Requirement: 业务入口检查具体权限
受保护的业务入口 MUST 通过统一授权边界检查 `can_*` 或现有领域权限代码所表达的具体能力。提案投票 MUST 检查该提案保存的通用选民规则结果，不得以界面主要身份、Django staff/superuser 标志、凭证、徽章、直接角色名称或快照作为旁路授权。

#### Scenario: 典守页面授权
- **WHEN** 成员请求受保护的典守页面
- **THEN** 系统检查对应的具体典守能力，而不是检查页面上显示的身份名称

#### Scenario: 对象级权限
- **WHEN** 成员操作一个具体资源或对一个具体提案投票
- **THEN** 授权检查包含该对象和对应规则上下文，任意资源范围或其他提案的能力不得替代本对象授权

### Requirement: 提案投票权必须由本提案的选民规则推导
OpenFGA 和统一授权服务 SHALL 根据提案保存的当前有效选民规则和 Django 权威事实推导该提案的投票权。系统 MUST NOT 为每个新角色或规则组合增加专用 `can_vote_*` 分支或合成角色。

#### Scenario: 社区共议允许贡献者
- **WHEN** 当前有效贡献者请求对选民规则明确包含贡献者的提案投票
- **THEN** 授权服务按该派生状态允许投票，不要求守约者资格或执衡者任期

#### Scenario: 守约事务要求执衡者
- **WHEN** 守约事务的选民规则要求有效守约者资格和执衡者任期
- **THEN** 只有同时满足两项当前条件的成员获得本提案投票权

#### Scenario: 专业事务要求对应资格
- **WHEN** 专业事务的选民规则还要求一个指定专业领域的有效资格
- **THEN** 缺少该领域资格的执衡者被拒绝，不得因具有其他专业资格而放行

#### Scenario: 选民规则无法计算
- **WHEN** 规则引用不存在的选择器、无效对象或未配置的授权模型
- **THEN** 系统失败关闭并拒绝投票，不得退回为社区共议或其他更宽松的规则

### Requirement: 典守能力必须来自典守者与显式权限
典守能力 MUST 由可复用的典守者关系和明确列出的具体权限推导，每项授权路径 MUST 在授权模型中可见、可测试和可审计。典守者关系与执衡者关系 MUST 相互独立。模型 MUST NOT 为特定个人、项目发起人或当前典守人员建立专属关系、硬编码主体或授权例外。

#### Scenario: 典守者执行典守操作
- **WHEN** 任一合格成员通过正常程序获得包含相应具体权限的典守者任命
- **THEN** OpenFGA 通过典守者与显式权限关系允许相应典守操作

#### Scenario: 执衡者没有典守者任命
- **WHEN** 一名成员具有有效执衡者任期但没有典守者任命
- **THEN** OpenFGA 不因执衡者身份授予任何典守能力

#### Scenario: 技术后台标志不得旁路授权
- **WHEN** 一个主体只有 Django `is_staff` 或 `is_superuser` 标志而没有相应 OpenFGA 业务关系
- **THEN** OpenFGA 不允许该主体执行 world 内的受保护业务操作

#### Scenario: 配置中出现个人专属主体
- **WHEN** 授权模型或 tuple 投影尝试为指定个人标识写入特殊管理关系
- **THEN** 模型校验或项目检查失败并报告该个人专属授权

### Requirement: 授权服务必须失败关闭
当 OpenFGA 是配置的授权后端时，store、model 或 tuple 缺失，请求失败，或检查结果无法确定，系统 MUST 拒绝受保护操作且不得回退到 Django 角色表放行。

#### Scenario: OpenFGA 不可用
- **WHEN** OpenFGA 请求失败或对应 world 未配置 store/model
- **THEN** 受保护页面与写操作被拒绝并返回可诊断但不泄露敏感信息的原因

### Requirement: 授权策略必须按 world 隔离
真实 world 与每个模拟 world MUST 使用各自的 OpenFGA store、model 配置和 tuple 集合。成员在一个 world 的守约者资格、执衡者任期、典守者任命或专业资格不得向另一个 world 传播能力。

#### Scenario: 同编号成员跨 world
- **WHEN** 两个 world 存在相同业务编号的成员且只有其中一个具有执衡者任期、典守者任命或专业资格
- **THEN** OpenFGA 只在对应 world 允许由该事实产生的能力

### Requirement: 新制度基线必须通过完整授权矩阵
未上线阶段 SHALL 使用可重复的授权矩阵和探针验证新制度的允许与拒绝结果。系统 MUST NOT 因为旧策略、旧 tuple 或兼容规则而放宽新制度的授权结果。

#### Scenario: 新制度矩阵发现错误
- **WHEN** 授权矩阵发现任一主体、能力、对象或 world 的结果不符合新制度规则
- **THEN** 新模型不得启用，并报告主体、能力、对象和 world
