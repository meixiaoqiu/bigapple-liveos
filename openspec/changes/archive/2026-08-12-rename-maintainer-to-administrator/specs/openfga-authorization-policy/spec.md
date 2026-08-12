## MODIFIED Requirements

### Requirement: OpenFGA 只接收必要的直接关系
OpenFGA tuple 投影 SHALL 只写入 Django 权威数据中当前有效且策略需要的守约者资格、执衡者任期、管理员任命、专业资格、角色权限绑定和通用选民规则所需的稳定参与关系。管理员直接关系 MUST 使用 `administrator`，不得写入旧 `maintainer` relation。

#### Scenario: 投影管理员
- **WHEN** 一个守约者直接持有管理员任命但没有执衡者任期
- **THEN** tuple 投影包含守约者资格和 administrator 直接关系，不包含执衡者或其他投票资格关系

#### Scenario: 重建 tuple
- **WHEN** 对同一 world 重复执行 tuple rebuild
- **THEN** 生成的直接关系集合稳定、无重复且不存在 maintainer relation

### Requirement: 管理能力必须来自管理员与显式权限
管理能力 MUST 由可复用的管理员关系和明确列出的具体权限推导，每项授权路径 MUST 在授权模型中可见、可测试和可审计。管理员关系与执衡者关系 MUST 相互独立。模型 MUST NOT 为特定个人建立专属关系、硬编码主体或授权例外。

#### Scenario: 管理员执行管理操作
- **WHEN** 任一合格成员通过正常程序获得包含相应具体权限的管理员任命
- **THEN** OpenFGA 通过 administrator 与显式权限关系允许相应管理操作

#### Scenario: 执衡者没有管理员任命
- **WHEN** 一名成员具有有效执衡者任期但没有管理员任命
- **THEN** OpenFGA 不因执衡者身份授予任何管理能力
