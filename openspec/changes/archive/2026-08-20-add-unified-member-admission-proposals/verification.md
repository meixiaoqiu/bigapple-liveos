# 验证记录

验证日期：2026-08-20

## 自动化验证

- 成员准入、权限、workspace、observer、simulation、world 隔离和统一提案定向测试：主定向集合 96 项通过，1 项因 SQLite 不支持行级锁而按预期跳过；补充 workspace 与 world 隔离测试 24 项通过；仿真 seed 测试 11 项通过。
- 完整 SQLite 隔离回归：1243 项通过，2 项因 SQLite 不支持 MySQL 行级锁语义而按条件跳过。
- `scripts/check_project.py --check-contracts`：通过；Compose 未挂载 sibling Docs，验证时将契约复制到仓库内临时目录，完成后已删除临时副本。
- sibling Docs 契约验证器：40 个 JSON 文件通过。
- Django system check：通过。
- 迁移漂移检查：通过，无待生成迁移。
- OpenSpec strict validation：通过。
- Docs 中英文生产构建：通过。
- Docs 孤立页面检查：意外孤立页面 0，未归入 sidebar 页面 0。
- Live OS 与 Docs 的 `git diff --check`：通过；Docs 仅有现有 LF/CRLF 转换提示。
- MySQL 并发测试：在明确创建的隔离数据库 `test_dev_big_real` 中实际运行事件反馈与统一提案并发锁测试，2 项全部通过且没有跳过；随后已删除该测试数据库。CI 已改为运行这两项测试，并移除已删除的旧财务测试模块引用。

## OpenFGA 发布

- 模型版本：`2026-08-20`
- 模型 SHA-256：`de3cbb88ddc4120b59680624feb24d9f280158d0c71f24c90e1afaede4cd3fcf`
- real model id：`01M0FDXB5GVMSPJFS8RATX0SBZ`
- simulation model id：`01M0FDXEKDQE653MTG9J4EPYAD`
- 发布命令只创建新模型，没有修改 `.env`。

## 浏览器人工验收

- real：发布准入政策；贡献者首次报名后以反对票形成拒绝终态；发布 2 票阈值的新版本后重新报名；管理员先投反对再改为赞成，票据从第 1 版变为第 2 版；第二名守约者投赞成后提案通过；管理员执行成功。
- simulation：先在无政策状态提交报名并确认等待配置；发布管理员选民政策后自动激活 1 项等待报名；管理员投赞成并执行成功。
- real 申请人 `qa-applicant-real-0820` 与 simulation 申请人 `qa-applicant-sim-0820` 均显示已接纳和守约者；数据库只读核对的任期分别为 2026-08-20 至 2027-08-20。
- world 隔离证据：real 有 2 项本次 QA 提案，simulation 有 1 项本次 QA 提案；申请人、任期与结果分别存在于对应 world。
- Chrome 控制台错误：real 0，simulation 0。
- 服务日志扫描：没有 Traceback、HTTP 500、旧 OpenFGA 模型版本或旧提案模块导入。
- 无权限执行、申请人自决排除、其他未迁移流程失败关闭同时由定向服务与 workspace 回归覆盖；浏览器页面只向满足相应权限的当前 Member 展示操作。

## 验收中修复的问题

- 删除报名页、登录说明和申请人工作台中“统一提案仍在迁移、决策不可用”的过时文案，改为当前统一提案状态与等待政策说明。
- 启动迁移增加 `INCONSISTENT_MIGRATION_HISTORY_DETECTED` 专用预检和准确重置提示；其他数据库错误不会被误报为清库场景。
- 修正 MySQL CI 并发测试清单：删除不存在的旧财务测试引用，加入统一提案并发改票测试。
