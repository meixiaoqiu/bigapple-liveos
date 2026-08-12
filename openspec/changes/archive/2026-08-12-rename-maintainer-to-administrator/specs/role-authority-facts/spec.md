## MODIFIED Requirements

### Requirement: 正式身份名称必须保持单一映射
系统 SHALL 使用贡献者 / Contributor、守约者 / Covenanter、管理员 / Administrator、执衡者 / Deliberator 作为四种正式产品称谓及英文语义映射。中文页面和中文说明 MUST 使用中文正式名称；代码语义、稳定标识和英文翻译 MUST 使用对应英文名称。旧称谓“典守者”及角色语义 `Maintainer` MUST NOT 作为运行时别名、兼容代码或正式文档内容保留。

#### Scenario: 中文页面展示身份
- **WHEN** 用户在中文页面查看成员身份
- **THEN** 页面只使用“贡献者、守约者、管理员、执衡者”表达对应状态、资格和职责

#### Scenario: 代码与英文翻译
- **WHEN** 系统表达管理员职责的英文语义
- **THEN** 使用 `Administrator` 或 `administrator` 对应语义，不使用 `Maintainer` 或 `maintainer`

### Requirement: 管理员职责不得产生执衡或投票资格
管理员 SHALL 仅获得明确绑定的管理能力。管理员身份 MUST NOT 自动产生执衡者任期、正式审议意见发表权或社区共议、守约事务、专业事务的投票资格。

#### Scenario: 只有管理员职责
- **WHEN** 一名守约者具有有效管理员任命但没有有效执衡者任期
- **THEN** 系统允许其执行明确授权的管理操作，但拒绝其以执衡者身份发表正式意见或参与非管理事务投票

#### Scenario: 管理员同时申请成为执衡者
- **WHEN** 具有有效管理员任命的守约者主动参加并通过执衡者资格考试
- **THEN** 系统创建独立执衡者任期，不修改管理员任命
