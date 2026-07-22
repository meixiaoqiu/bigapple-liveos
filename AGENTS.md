# Big Apple Live OS Codex 指南

## 适用范围

本文件规则适用于 `big-apple-live-os/` 仓库。

`big-apple-live-os/` 是 Big Apple 的 Django 权威系统。不要把上级工作区目录当成单一 Git 仓库处理；本仓库和 `../bigapple-docs/` 是相互独立的仓库，技术契约位于 `../bigapple-docs/static/technical-contracts/`。

## 开始前阅读

- Live OS 编码任务先读 `../bigapple-docs/docs/development/ai-guide.md`，再读本次任务直接相关的文档和代码。
- API、schema 或 payload 变更必须先检查 `../bigapple-docs/static/technical-contracts/` 中对应 contract，再修改 Live OS 实现。
- 视觉主题任务只读取 `../bigapple-docs/docs/development/theme-system.md` 和相关设计文档；非主题任务不要加载大型设计资料或导出目录。
- 远程开发环境、Docker、启动脚本、服务器预览问题才需要读取 `../bigapple-docs/docs/development/remote-dev.md`。

## 安全边界

- 默认只在当前仓库内工作；只有 API、schema 或 payload 任务需要读取 `../bigapple-docs/static/technical-contracts/`。
- 不要输出密钥、token、密码、API key、cookie 或私密环境变量。
- 不要使用 `sudo`。
- 未经明确允许，不要执行破坏性命令，例如 `rm -rf`、`docker volume rm`、`drop database` 或批量删除命令。
- 保留不是你创建的未提交改动；修改前先检查 `git status --short`。

## 编辑规则

- 优先做小而明确的改动，先理解现有结构，再增加抽象。
- 优先使用项目已有脚本、已有配置和已有测试命令。
- 会改变权威状态的 service 函数必须写 docstring。
- 含义不明显的 model 字段必须写 `help_text`。
- view 保持轻量，状态变化放进对应领域服务模块；不要新增 `core.services` 这种大杂烩服务门面。
- 权威模型仍归属 `core` app，但模型定义必须按领域放在 `core.models` 包下；`core.models.__init__` 只作为导出入口。
- 新增依赖前必须说明原因。
- 不要把密钥或真实隐私数据写入仓库。

## 忽略和少读范围

避免读取或修改生成文件、缓存目录、依赖目录和大型资料，除非本次任务明确需要：

- `.git`
- `.venv`
- `node_modules`
- `vendor`
- `__pycache__`
- `.pytest_cache`
- `staticfiles`
- `media`
- `logs`
- `uploads`
- `output/`
- `temp/`
- `theme/static/css/dist/styles.css`

修改 observer 模板中的 Tailwind class 后，才需要运行 `python manage.py tailwind build` 并提交编译后的 `theme/static/css/dist/styles.css`。

## 文档同步

模型、流程、权限、Admin、仿真、Observer、API 或 AI 边界变化后，按 `../bigapple-docs/docs/development/ai-guide.md` 中的“必须同步更新的文档”表更新对应文档。

公开项目文档、架构说明、产品规划、路线图、运行入口边界、产品功能说明、API 文档、数据库表结构、治理交互边界和开发文档已迁移到 sibling 仓库 `../bigapple-docs/`。修改这些公开文档时进入 `../bigapple-docs/`，不要在本仓库重新创建 `docs/` 下的 Markdown 文档。

## 验证提醒

- 修改后优先运行最小相关检查或测试。
- Live OS 行为变更按 `../bigapple-docs/docs/development/ai-guide.md` 中的测试建议验证。
- 常用完整本地回归：

```powershell
.\.venv\Scripts\python.exe manage.py test core live_os observer workspace simulation simulation_lab worlds --settings=live_os.test_settings
```

- 常用基础检查：

```powershell
.\.venv\Scripts\python.exe scripts\check_project.py
.\.venv\Scripts\python.exe manage.py check --settings=live_os.test_settings
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=live_os.test_settings
git diff --check
```
