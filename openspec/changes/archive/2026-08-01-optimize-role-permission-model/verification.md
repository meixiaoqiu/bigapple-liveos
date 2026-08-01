# 角色与权限新制度验收记录

## 仿真基线

验收 world：`simulation0001`

- `reset_role_permission_baseline --world-id simulation0001 --format json`：PASS
  - 清除了旧基线中的角色、任命、权限绑定、角色事件与专业资格试验数据。
  - 装载后只保留三个规范角色：正式成员、议事者、维护者。
  - 装载后有七条规范角色任命、三个专业领域和一条财务专业资格。
  - OpenFGA tuple 重建：PASS。
- OpenFGA 模型预检：PASS。若 store、model 或模型关系不兼容，重置命令会在清理仿真数据前失败关闭。

## 运行时授权矩阵

| 场景 | 预期 | 结果 |
| --- | --- | --- |
| 维护者检查维护能力 | 允许 | PASS |
| 议事者检查维护能力 | 拒绝 | PASS |
| 议事者参与普通议事提案 | 允许 | PASS |
| 仅维护者参与普通议事提案 | 拒绝 | PASS |
| 具有财务资格的议事者参与财务专业提案 | 允许 | PASS |
| 缺少财务资格的议事者参与财务专业提案 | 拒绝 | PASS |

普通议事与财务专业议事均在 `simulation0001` 创建短期验收提案后，通过
`openfga_authorization_probe` 实际检查。验收提案属于可重置仿真数据，将在下一次
`reset_role_permission_baseline` 时清除。

## 界面验收

- 仿真观察页：PASS。迁移后重建 `big-apple-sim` 容器，页面可正常打开。
- 议事者公开资料：PASS。显示“正式成员”和“议事者”，并显示本人申请的一年任期。
- 维护者公开资料：PASS。显示“正式成员”和“维护者”，不显示“议事者”。
- 旧制度标签：PASS。产品源码静态检查和页面回归测试均未发现旧角色名称。

## 定向自动测试

以下定向回归已通过：

```powershell
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py test core.tests.test_identity_display core.tests.test_role_usage_check core.tests.test_role_permission_baseline observer.tests.test_member_profiles workspace.tests.test_public_profile --settings=live_os.test_settings
```

结果：45 项通过。

## 文档与技术契约

- OpenSpec 主规格：PASS。已将角色权威事实、OpenFGA 授权策略和身份显示三个增量规格同步为仓库主规格；`openspec validate --strict` 通过。
- sibling 文档：PASS。架构、数据表、产品入口、维护后台、仿真环境变量和页面说明均已同步；公开文档与 technical contracts 中不再出现旧角色名称。
- 技术契约：PASS。一次性 Python 容器运行 `static/technical-contracts/scripts/validate_contracts.py`，检查 38 个 JSON 文件。
- 文档站构建：PASS。`npm.cmd run build` 同时完成 `zh-Hans` 与 `en` 静态站构建。

## 最终回归与静态检查

| 检查 | 结果 |
| --- | --- |
| 定向角色与显示测试 | PASS，45 项。 |
| 修正的观察页、零起点和仿真重置测试 | PASS，101 项。 |
| 完整 Django 回归 | PASS，1,081 项。 |
| `scripts/check_project.py` | PASS。 |
| `manage.py check --settings=live_os.test_settings` | PASS。 |
| `makemigrations --check --dry-run --settings=live_os.test_settings` | PASS，无待生成迁移。 |
| `git diff --check` | PASS。 |

完整回归中的 OpenFGA 不可用提示来自专门的失败关闭测试；这些测试断言授权被拒绝，未表示生产验收失败。

## 终审修复补充

- 旧选民范围迁移：已增加保护函数；发现任意遗留提案时迁移明确失败，不再把旧范围默认解释为普通议事。已新增迁移保护单元测试。
- 专业资格：已新增 `governance.manage_professional_qualifications` 明确维护权限；录入和撤销服务均通过统一授权边界校验，普通成员的确认与撤销路径已新增拒绝测试。
- 规范角色目录：`Organization.role_catalog_key` 作为唯一稳定目录标识；角色任命、当前事实查询、OpenFGA tuple 重建与角色盘点均不再只按显示名称或组织名称识别规范角色。其他组织的同名内置角色会被拒绝，不能签发正式成员编号凭证。
- 专业提案测试：测试维护者通过 `ensure_maintainer_role()` 初始化角色及完整维护权限；专业提案策略测试 9 项 PASS。
- 角色用途审计：重新核对全部 28 处直接角色判断，更新 8 个漂移位置并移除 1 个已不再存在的直接角色名判断；审计测试 3 项和 `scripts/check_role_usage.py` 均为 PASS。
- OpenFGA 启动验收：real 与 sim 模型重新发布，tuple 重建与维护能力探针 PASS；`start.bat` 完整启动退出码为 0。
- 项目检查：`scripts/check_project.py`、Django system check、迁移漂移检查和 `git diff --check` 均为 PASS。
- 完整 Docker 回归：2026-07-31 运行 1,081 项测试，全部 PASS。
- Docs 一致性终审：清除架构总览、AI 开发指南、维护后台和成员工作台中的旧角色、旧服务与旧命令说明；验收矩阵全部映射到真实测试模块。矩阵相关 88 项测试 PASS，Docs 中文与英文站点重新构建 PASS。

## 改动范围

本变更覆盖角色目录、任命与专业资格、提案选民政策、OpenFGA 模型与 tuple 投影、运行时授权调用、身份显示、仿真基线、迁移、测试、OpenSpec 过程记录和 sibling 文档。未修改真实 world 业务数据；运行时验收只使用可重置的 `simulation0001`。
