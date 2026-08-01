# 正式角色命名与通用选民规则验收记录

## 实现完整性

- 角色命名：PASS。运行时代码、界面、测试、OpenFGA 模型和正式项目文档统一使用贡献者 / Contributor、守约者 / Covenanter、典守者 / Maintainer、执衡者 / Deliberator。
- 权威事实：PASS。贡献者仅为派生状态；守约者资格、典守者任命、执衡者任期和专业资格保持独立。
- 通用选民规则：PASS。提案引用不可变规则版本和条件快照，提案类型限制可选模板，条件树只允许封闭选择器及 `ALL`、`ANY`、`NOT`。
- 制度模板：PASS。社区共议、守约事务、专业事务和典守事务均有明确模板；典守者不自动获得执衡者投票权。
- OpenFGA：PASS。具体 proposal 统一使用 `can_vote`，由 Django 当前规则与 OpenFGA 投影双重检查，异常时失败关闭。
- 迁移边界：PASS。未上线旧数据不做兼容转换；迁移发现旧角色或旧提案选民数据时明确中止，仿真世界可重置，真实 world 不被自动清理。

## 自动化验证

| 检查 | 结果 |
| --- | --- |
| 选民规则与相关定向测试 | PASS，65 项。 |
| 仿真世界重置测试 | PASS，20 项。 |
| 旧测试标识符重命名后的相关回归 | PASS，69 项。 |
| 完整 Django 回归 | PASS，1,162 项。 |
| `scripts/check_project.py` | PASS。 |
| Django system check | PASS，无问题。 |
| 迁移漂移检查 | PASS，无待生成迁移。 |
| 旧制度名称静态审计 | PASS；运行时、测试、主规格和正式文档无残留，历史迁移与 OpenSpec 过程记录除外。 |
| Live OS `git diff --check` | PASS。 |
| Docs `git diff --check` | PASS，仅换行符提示。 |
| 中英文文档站构建 | PASS，`zh-Hans` 与 `en` 均完成。 |
| Technical contract JSON 校验 | PASS，38 个 JSON 文件。 |
| OpenSpec 严格校验 | PASS。 |

完整回归日志中的 OpenFGA 不可用提示来自专门验证失败关闭行为的测试，测试结果为通过。

## 本地 OpenFGA 配置

新仿真授权模型已成功发布，仿真重置测试和完整回归在单次 Docker 环境覆盖下通过。当前 `.env` 仍指向旧模型时，启动脚本会正确拒绝启动；需要将 `OPENFGA_SIM_AUTHORIZATION_MODEL_ID` 更新为本次 bootstrap 输出的新模型 ID，再重新运行 `start.bat`。本变更未自动修改 `.env`。

## 启动链路补充验收

- 修正 `0041` 的仿真迁移边界：simulation world 自动清理旧提案及旧角色权威事实后继续迁移；real/control 发现同类旧数据时仍失败关闭。
- 修正仿真基线初始化顺序：受控装载阶段先依据 Django 权威事实建立典守者和专业资格，随后重建 OpenFGA tuple，不为日常业务增加授权旁路。
- `simulation0001` 新基线重建：PASS，3 个规范角色、7 条任命、1 条专业资格、37 条 OpenFGA tuple。
- `start.bat`：PASS，退出码 0；仿真典守者 `governance.view_admin` 探针为 `allowed=true`，其他候选人均为 `false`。
- 清除旧仿真成员壳及其旧凭证：PASS；真实 world 未修改。

## 文档与规格

- technical contracts 先于实现更新并通过示例校验。
- sibling 文档仓库的架构、治理边界、数据库结构、产品页面、开发指南和验收矩阵已同步。
- 四份 delta spec 已核对并同步到主规格；新增 `configurable-electorate-rules` 主规格，更新 OpenFGA、角色权威事实和角色展示主规格。
- 所有项目文档与 OpenSpec 正式规划内容均遵守中文文档规则；代码、协议、稳定语义名和 OpenSpec 结构关键字保留必要英文。
