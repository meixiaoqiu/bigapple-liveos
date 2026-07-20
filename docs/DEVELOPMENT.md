# 开发说明

## 本地依赖

- Docker Desktop
- 已存在的 Docker network：`dev-net`
- 已存在的 MySQL 容器：`mysql97`
- 已存在的 nginx 容器：`nginx`
- 可连接的 MySQL 数据库，推荐 `utf8mb4` 字符集和 `utf8mb4_0900_as_cs` 排序规则

## 安装

```bat
copy .env.example .env
notepad .env
```

## 数据库连接配置

本地运行推荐填写：

```text
.env
```

格式：

```dotenv
DATABASE_URL=mysql://用户名:URL编码后的密码@mysql97:3306/数据库名?charset=utf8mb4
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,bigadmin.local,bigreal.local,bigsim.local
```

Docker 开发模式下，Django 进程运行在 `big-apple-admin`、`big-apple-real`、`big-apple-sim` 容器内，MySQL host 应写同一 `dev-net` 网络里的容器名 `mysql97`。如果写成宿主机视角的 `127.0.0.1`，容器内会尝试连接自己而不是 MySQL。

如果需要使用 nginx gateway URL，请确认 Windows hosts 文件包含：

```text
127.0.0.1 bigadmin.local
127.0.0.1 bigreal.local
127.0.0.1 bigsim.local
```

`BIG_APPLE_CONTRACTS_ROOT` 默认使用 `../big-apple-contracts`，通常不需要手动设置；当前运行时代码不直接读取 contracts 文件，普通 CI 和 Live OS 自检也不要求相邻 contracts 仓库存在。

`start.bat` 会检查 Docker Desktop、`.env`、`dev-net`、`mysql97`、`nginx` 和本地域名映射。它只启动和连接已有容器，不会创建数据库容器、nginx 容器、Docker network 或数据卷。

## 常用命令

无第三方依赖的仓库检查。默认只检查 Live OS 仓库自身：

```bash
python scripts/check_project.py
```

涉及 API、schema 或 payload 兼容性时，再显式检查 contracts：

```bash
python scripts/check_project.py --check-contracts
```

启动 Docker 开发环境：

```bat
start.bat
```

`start.bat` 是本地开发推荐启动方式。它会：

- 切换到 `big-apple-live-os` 目录。
- 校验 `.env` 中的 `DATABASE_URL=mysql://...@mysql97:3306/...`。
- 检查 Docker Desktop 是否可用。
- 检查 `dev-net` 网络是否存在。
- 启动已有的 `mysql97` 容器并连接到 `dev-net`。
- 等待 `mysql97` health check 通过。
- 通过 `docker compose -f docker-compose.dev.yml up -d --force-recreate big-apple-admin big-apple-real big-apple-sim` 启动三个 Django 站点。
- 启动已有的 `nginx` 容器并连接到 `dev-net`。
- 输出直连 Django 和 nginx gateway 访问地址。
- 使用 `--noreload` 启动 Django 开发服务，避免 autoreload 在 Docker 开发环境中派生额外进程。模板小改后刷新页面即可看到；Python 代码改动后需要重新运行 `start.bat` 或手动重建对应服务。

容器启动后，control plane 和 world 迁移命令通常通过 `big-apple-admin` 执行：

```bat
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py check --settings=live_os.settings_admin
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py makemigrations --check --dry-run --settings=live_os.settings_admin
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py migrate --settings=live_os.settings_admin
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py migrate_world realworld --noinput --settings=live_os.settings_admin
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py migrate_world simulation0001 --noinput --settings=live_os.settings_admin
```

创建 Django Admin 超级用户：

```bat
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py createsuperuser --settings=live_os.settings_admin
```

写入后台预览用演示数据：

```bat
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py seed_demo --world-id realworld --settings=live_os.settings_admin
```

`seed_demo` 是幂等命令，重复执行不会重复插入同一批演示记录。它不会删除任何已有数据。运行时启用 world 数据库路由后，直接执行必须显式传入 `--world-id`；被 `seed_world` 或 `smoke_workflow` 调用时会复用已绑定的 world 上下文。
当前 seed 数据包含 `bigapple001据点执行计划`，可在 Admin 中编辑计划、版本、节点、依赖、需求和容量影响，并在观察台中查看主线进度。

## 前端资源

本项目使用 Django 生态方式接入前端工具：

- `django-tailwind`：管理 `theme` Django app 中的 Tailwind 构建。
- `daisyUI`：作为 Tailwind 插件配置在 `theme/static_src/src/styles.css`。
- `django-htmx`：通过 `django_htmx.middleware.HtmxMiddleware` 和模板标签加载 HTMX。
- 主题模板：通过 `ACTIVE_THEME`、`THEME_CONFIGS` 和 `templates/themes/<theme_key>/` 管理页面展示层。完整规则见 `docs/theme-system.md`。

前端源码位置：

```text
theme/static_src/
```

编译后的 CSS 位置：

```text
theme/static/css/dist/styles.css
```

首次拉取或重新安装依赖后：

```bash
python manage.py tailwind install
```

修改模板或 Tailwind class 后，需要重新构建：

```bash
python manage.py tailwind build
```

## Runtime 错误页

固定 world runtime 的普通网页入口使用统一友好错误页：

- `live_os.error_handlers` 提供 400 / 403 / 404 / 500 handler 和 405 渲染函数。
- `live_os.middleware.FriendlyErrorPageMiddleware` 将普通网页中的 403 / 404 / 405 响应替换为 `templates/errors/runtime_error.html`。
- `/api/` 和 `/admin/` 被 middleware 跳过，避免把 API 或后台错误响应改成普通网页。
- `/logout/` 必须保持 POST-only；GET `/logout/` 返回 405 友好页，不执行退出。

修改错误页模板中的 Tailwind / daisyUI class 后，需要运行：

```bash
python manage.py tailwind build
```

开发时也可以使用 watch：

```bash
python manage.py tailwind start
```

当前 Dockerfile 不安装 Node.js。修改 Tailwind 源样式时，仍建议在宿主机 Python/Node 开发环境中运行上述 Tailwind 命令，或单独补充前端构建容器。

`node_modules/` 不入库；`package.json`、`package-lock.json`、Tailwind 源文件和编译后的 `styles.css` 入库，方便没有前端上下文的开发者和 AI agent 直接运行 Django 页面。

主题模板约定见 `docs/theme-system.md`。当前主 fallback 主题是 `default_game`。

跑通第一条 API 业务闭环：

```bat
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py smoke_workflow --world-id realworld --seed-demo --settings=live_os.settings_admin
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py smoke_workflow --world-id simulation0001 --settings=live_os.settings_admin
```

`smoke_workflow` 会在指定 world 内通过 HTTP API 完成：

1. 查询开放任务
2. 领取任务
3. 提交劳动
4. 验收任务
5. 查询积分流水
6. 查询事件流
7. 查询观察台摘要

该命令默认验证 `realworld`，也可以用 `--world-id simulation0001` 验证仿真世界。真实世界默认不会写入演示数据；需要本地演示起点时显式加 `--seed-demo`，或先运行 `seed_demo --world-id realworld`。仿真 world 会自动使用 `seed_world` 准备隔离演示数据。它会在目标 world 数据库中新建一个 `task-smoke-*` 任务，用于开发自检，不用于生产数据。

跑通自动仿真闭环：

```bat
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py run_simulation_smoke --world-id simulation0001 --settings=live_os.settings_admin
```

`run_simulation_smoke` 只接受仿真 world，会拒绝 `realworld`。它默认复用 `seed_world` 准备幂等演示数据，然后创建 `SimulationRun`，自动推进主线计划，检查 `SimulationTurn`、仿真 `Event`、节点状态和失败反馈是否完整；启用 world 数据库路由时，还会检查 `realworld` 关键表记录数没有变化。它验证的是自动推演闭环，不替代上面的 HTTP 任务业务闭环。

跑通零起点自媒体报名与启动门槛仿真：

```bat
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py seed_world simulation0001 --template zero_start --settings=live_os.settings_admin
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py run_zero_start_simulation --world-id simulation0001 --hours 168 --settings=live_os.settings_admin
```

`zero_start` 模板只预置一个发起人、一个极简计划和一个已发布计划版本，不预置任务、资源、候选场地或成熟成员池。启用 `BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_ENABLED=true` 时，这个发起人就是配置的仿真 bootstrap admin 登录成员；未启用时才使用非交互 fallback 发起人。`run_zero_start_simulation` 会按整数小时驱动虚拟主体通过真实 world URL 提交成员报名和合作方报名表单，生成自媒体主动报名、初筛、候选、备用、项目拒绝、主动退出、成员能力矩阵和文件签署方矩阵记录，用于下一轮从真正 0 点继续推演。成员报名表单使用 `role_gap`、`availability_slots`、动态问答和提交确认；历史小时字段只作为仿真兼容数据随 POST 一起带入，不再是页面主输入。默认 168 小时只是一个观察窗口；如果启动门槛未满足，run 会保持 `running` 并允许再次执行命令继续推进同一个 run。报名密度会随虚拟曝光时间增加，而不是平均分布。当前 driver 会验证页面和 HTML 表单字段并通过 HTTP POST 提交；浏览器抽样验证后续接入同一 driver 边界。

启动门槛满足后，同一个 `zero_start` run 会继续进入 `pre_engineering` 工程前置阶段，而不是立刻结束。该阶段会把候选场地池、并网预筛、场地合法性与附条件租赁审查、结构/光伏/电气/施工/验收责任文件取得过程写入 `SimulationTurn.metadata` 和公开仿真事件；只有工程前置责任闭环完成后，run 才会进入 `completed`。

归档一次已结束的仿真运行：

```powershell
.\.venv\Scripts\python.exe manage.py archive_simulation_run --world-id simulation0001 --run-id sim-run-xxx
.\.venv\Scripts\python.exe manage.py archive_simulation_run --world-id simulation0001
```

归档命令会把来源 world 中的 `core` 域模型逐表导出到 `var/simulation_archives/{snapshot_id}/raw/`，同时在 control DB 写入 `SimulationSnapshot` 和 `SimulationSnapshotItem` 查询索引。`raw_archive` 是不可变原始证据，`normalized_archive` 是可迁移查询索引。

归档时可以补充正式复盘字段：

```powershell
.\.venv\Scripts\python.exe manage.py archive_simulation_run --world-id simulation0001 --run-id sim-run-xxx --scenario zero_start --purpose "验证零起点自媒体报名筛选" --review-conclusion "候选池形成不等于启动门槛满足"
```

如果一次已结束仿真没有归档价值，必须显式放弃归档，不能直接启动下一轮：

```powershell
.\.venv\Scripts\python.exe manage.py discard_simulation_run --world-id simulation0001 --run-id sim-run-xxx --reason "参数误设，作为调试运行放弃归档。"
```

`archive_simulation_run` 和 `discard_simulation_run` 都会写入 control DB 的 `SimulationRunDisposition`。`run_simulation_smoke` 和 `run_zero_start_simulation` 会拒绝在同一个仿真 world 中覆盖已结束但未处置的 run；仍为 `running` 的零起点 run，或旧版本留下的“启动门槛未满足”业务失败 run，不需要先处置，下一次执行会继续追加小时级推进记录。

如果一个 `running` run 因模型缺陷或参数误设已经没有继续价值，先在 `/admin/simulation-lab/` 的 run 详情页填写原因并“中止本轮仿真”。中止后的状态是 `aborted`，此时才能继续归档或废弃。

校验一个已归档快照：

```powershell
.\.venv\Scripts\python.exe manage.py verify_simulation_snapshot snapshot-xxx
```

校验命令会检查 `manifest.json`、逐模型 raw JSON 文件 SHA-256、raw 清单稳定哈希、逐模型记录数、`report.html` 路径和 control DB 中的标准化明细数量。

也可以通过 Django Admin 下的仿真实验后台选择仿真槽位、处理待归档 run、启动或继续零起点仿真：

```text
http://bigadmin.local/admin/simulation-lab/
```

已归档快照、标准化明细和处置记录的罗列查询归属 `/admin/` 首页的“仿真”一级菜单；仿真实验后台不再重复承担这些列表页职责。待处置 run 在归档或废弃前可以打开详情页，审阅失败证据、修订建议、结构化变更集和推进日志。

当前本地开发可以只使用 `simulation0001` 这一个仿真槽位。槽位中的运行态数据可以随着下一轮仿真重置或覆盖，但已结束 run 必须先在页面或命令中归档/废弃；归档后的正式历史来自 `SimulationSnapshot`、`SimulationSnapshotItem`、`SimulationRunDisposition` 和 `var/simulation_archives/`，不是来自永久在线的仿真数据库。

启动后访问：

```text
http://127.0.0.1:20100/admin/
http://bigadmin.local/admin/
```

观察台页面：

```text
http://127.0.0.1:20101/
http://bigreal.local/
```

成员工作台页面：

```text
http://127.0.0.1:20101/workspace/
http://127.0.0.1:20102/workspace/
```

真实世界和仿真世界 runtime 不暴露 `/live-admin/` 或 `/admin/`。底层维护、仿真实验和高影响操作统一进入 control plane 的 `http://127.0.0.1:20100/admin/`；成员日常使用 `/workspace/`，公开观察使用公开首页 `/`。`/apply/` 和 `/apply/partner/` 已删除，正式成员报名移至 `/workspace/apply/`，合作方报名后续单独设计。

### Workspace 成员报名审核模块

`/workspace/` 在正式成员工作台之外，为具备 `governance.view_admin` 权限的治理成员提供成员报名审核入口。普通正式成员、待审核报名人、未绑定 `Member` 的 Django staff/superuser 都看不到入口，直接访问审核 URL 返回 403。

**未登录入口**：未登录用户 GET `/workspace/` 不再返回 403，而是渲染 `workspace/login_required.html` 入口门禁页（200），展示注册、登录和观察台入口。登录后才进入个人 workspace。不改变已登录成员的权限判断逻辑。

**注册与报名分离**：`/register/` 只创建 `User` + `Member` + `ROLE_BIG_APPLE_MEMBER`，不写公开 Event。`/workspace/apply/` 是登录后的正式成员报名入口，报名表不再包含账号密码字段。

**完整 workspace 判断**：`member_has_full_workspace_access()` 当前基于 active `ROLE_FORMAL_MEMBER` 角色判断（`SUSPENDED` / `EXITED` 作为 veto），不再基于 `Member.status`。`/workspace/apply/` 的"已是正式成员"判断同理。不要用 `Member.status` 判断正式成员权限。

`/workspace/apply/` 提交成员报名后，系统自动创建 MemberApplication 和 member_admission Proposal，提案直接进入 VOTING 状态。不存在独立的人工审核动作——准入完全由提案生命周期驱动。

**招募方向维护** (`/workspace/recruitment/`)：治理成员可以进行受限招募方向管理——`action=create` 新增 certificate/public/active 的招募方向模板（自动填充 `metadata.recruitment`），`action=update` 修改已有方向的配置。该页面不开放完整 CredentialTemplate CRUD：不允许删除、不允许改 credential_type / visibility / status。新增和更新都不会发放 CredentialGrant。修改后 `/workspace/apply/` 的表单卡片立刻反映新配置。普通成员无法访问该页面。

member_admission 是 yes/no 二元表决，使用严格多数决：赞成票超过 eligible voters 半数时立即通过；反对票超过 eligible voters 半数时立即失败，并自动将关联 MemberApplication 设为 REJECTED。未形成多数前保持表决中；截止仍未通过则失败。分母始终是 `eligible_voters_snapshot_json` 的人数，不是已投票人数。普通 proposal 规则不变。

```text
GET  /workspace/applications/                                          # 报名列表（按准入进度筛选：投票中/已通过待执行/已接纳/未通过已拒绝/全部）
GET  /workspace/applications/<application_id>/                         # 报名详情（申请人资料 + 准入提案 + 投票 + 执行）
POST /workspace/proposals/<proposal_id>/vote/                          # 成员准入投 yes/no；反对必须填写理由
POST /workspace/proposals/<proposal_id>/execute/                      # 执行已通过准入提案
```

不存在以下路由：

```text
POST /workspace/applications/<application_id>/review/                  # 已删除，不允许单人标记审核状态
POST /workspace/applications/<application_id>/create-admission-proposal/  # 已删除，提案在报名时自动创建
```

### 公开反馈模块

公开反馈是注册用户的公众参与入口，不是治理提案，不直接改变权威状态。

```text
GET  /feedback/                    # 公开反馈列表，未登录可访问
GET  /feedback/new/                # 新建反馈表单，需登录
POST /feedback/new/                # 提交反馈，创建 CommunityFeedback + 普通公开 Event
GET  /feedback/<feedback_id>/      # 反馈详情，hidden 对普通用户 404
POST /feedback/<feedback_id>/respond/  # 治理成员回应、隐藏或关联提案
```

状态变化必须通过 `core.feedback_services`：`submit_feedback()`、`respond_to_feedback()`、`hide_feedback()`、`link_feedback_to_proposal()`。Feedback 不写 `SystemEvent` 哈希链；提交、回应和关联提案只写普通公开 `Event`。隐藏不写新的公开 Event，并会把该反馈既有公开 Event 转为 internal。

相关测试：

```powershell
.\.venv\Scripts\python.exe manage.py test feedback observer --settings=live_os.test_settings
```

### 公开财务模块

公开财务用于处理成员报销、财务审核和付款流水。它是具体业务流程，不是治理提案本身；只有高影响预算、异常争议或规则变更才应升级为 Proposal。

```text
GET  /finance/                                      # 公开财务页，未登录可访问
GET  /workspace/finance/claims/                     # 报销列表；普通成员看自己，财务成员看全部
GET  /workspace/finance/claims/new/                 # 新建报销表单
POST /workspace/finance/claims/new/                 # 提交报销，创建 ExpenseClaim + Event + SystemEvent
GET  /workspace/finance/claims/<claim_id>/          # 报销详情
POST /workspace/finance/claims/<claim_id>/review/   # 财务审核，需 finance.review
POST /workspace/finance/claims/<claim_id>/pay/      # 标记付款，需 finance.pay
POST /workspace/finance/claims/<claim_id>/withdraw/ # 申请人撤回
```

状态变化必须通过 `core.finance_services`：`submit_expense_claim()`、`review_expense_claim()`、`mark_expense_claim_paid()`、`withdraw_expense_claim()`。不要在 view、Admin 或测试里直接改 `ExpenseClaim.status` 或直接创建 `FinanceReview` / `FinanceTransaction` 来表达真实流程。

财务权限由 `core.finance_setup.ensure_finance_roles()` 幂等初始化。`finance.review` / `finance.pay` / `finance.view_private` 都是 RolePermission；授予带 `finance.*` 权限的角色前，目标成员必须已经拥有 `ROLE_FORMAL_MEMBER`。申请人不能审核或付款自己的报销；拒绝必须填写理由。`FinanceTransaction` 只追加，错误应通过后续冲正流水处理。

相关测试：

```powershell
.\.venv\Scripts\python.exe manage.py test core.tests.test_finance --settings=live_os.test_settings
```

成员公开资料自助维护：

```text
GET  /workspace/profile/                    # 成员自助资料维护页
POST /workspace/profile/update/             # 更新公开姓名/头像 URL
```

当前成员（含 pending applicant）可维护公开姓名和头像 URL，展示在 `/u/<member_no>/`。不能编辑角色/权限/治理身份，不提供简介和可见性自助编辑。

正式接纳只能通过 proposal vote -> passed -> execute_proposal 完成。未通过/拒绝来自提案投票结果或提案生命周期（过期未达票数），不存在单人点击的“拒绝报名”按钮。未绑定 Member 的 Django staff/superuser 不能绕过治理成员身份要求。


观察台：

```text
http://127.0.0.1:20101公开首页 `/`
```

`/` 当前是固定 world 的时间线指挥台式总览，使用 Tailwind、daisyUI 和 HTMX 渲染。首页重点展示今日事件时间线、核心指标、风险侧栏、容量评估、高负载岗位和待处理争议。`/events/` 是公开社区事件流，普通观察者的主入口；事件详情展示语义摘要（非数据库字段表）和带现场验证的审计证明。`/event-ledger/` 是底层 SystemEvent 哈希链审计账本，作为隐藏高级审计入口保留，不在普通导航中展示。导航只指向页面内只读区域或公开只读 API，不提供后台入口。

仿真实验后台负责仿真 POST 动作；Observer 只负责观察：

```text
POST /admin/simulation-lab/advance/
POST /admin/simulation-lab/run-until-failure/
```

`/admin/simulation-lab/advance/` 当前是待遗弃的仿真写库边界自检入口，不是仿真推进功能；未绑定 simulation run 时不会写入真实世界数据。若后续删除，应连同 URL、view、页面按钮和页面级测试一起删除。命令行工具只用于开发自检，不作为仿真产品形态。

后台界面已设置为中文：

- Django 语言：`zh-hans`
- 时区：`Asia/Shanghai`
- Admin 站点标题：`大苹果 Live OS 管理后台`
- 核心模型、字段、枚举显示名：中文

如果后台看起来像纯 HTML，或者标题仍然显示 `Django administration`、`Site administration`，说明当前访问到的服务进程没有正确加载本地开发配置。按下面步骤处理：

1. 停掉当前 Web 容器或旧的宿主机 `runserver` 进程。
2. 确认从 `big-apple-live-os` 目录启动。
3. 重新启动：

```powershell
docker compose -f docker-compose.dev.yml down
start.bat
```

4. 在浏览器中强制刷新 `http://127.0.0.1:20100/admin/` 或 `http://bigadmin.local/admin/`。

本地开发在未设置 `BIG_APPLE_ENV` / `DJANGO_ENV` 时默认按 `local` 处理，允许开发用 secret 和 `DJANGO_DEBUG=true`，这样 Django runserver 会提供 Admin 所需的 CSS/JS 静态资源。

非本地环境必须显式设置：

- `BIG_APPLE_ENV=production` 或 `DJANGO_ENV=production`
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG=false`
- `DJANGO_ALLOWED_HOSTS`
- 通过 HTTPS 代理访问表单页面时设置 `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_SECURE_SSL_REDIRECT=true`
- `DJANGO_SESSION_COOKIE_SECURE=true`
- `DJANGO_CSRF_COOKIE_SECURE=true`
- `DJANGO_SECURE_HSTS_SECONDS` 为正整数

生产环境还必须配置正式静态资源服务。

API 闭环测试：

```bat
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py test core live_os observer workspace simulation simulation_lab worlds --settings=live_os.test_settings
```

测试设置位于 `live_os/test_settings.py`，默认使用 SQLite 内存库，不依赖本地 MySQL 连接。

## 文档同步规则

任何行为变化都应在同一个变更中更新文档：

- 模型或表结构变化：更新 `docs/DATABASE_SCHEMA.md`
- 项目执行计划或主线节点规则变化：更新 `../bigapple-docs/docs/product/project-plan.md`
- API 变化：先更新 contracts，再更新 `docs/API.md`
- 架构边界变化：更新 `../bigapple-docs/docs/architecture/overview.md`
- 新开发流程：更新 `docs/DEVELOPMENT.md`
- AI 协作规则变化：更新 `docs/AI_DEVELOPMENT_GUIDE.md`
- 仿真推进规则或页面入口变化：更新 `../bigapple-docs/docs/product/simulation.md`
- 观察台前端布局、HTMX partial 或 Tailwind/daisyUI 构建方式变化：更新 `../bigapple-docs/docs/product/observer.md` 和本文件

## 契约变更规则

不要先在 Live OS 里发明响应字段。变更顺序必须是：

1. 修改 `big-apple-contracts`
2. 修改 Live OS 实现
3. 更新示例和测试
4. 更新文档

## World-Scoped Local URLs

World routing now separates the control database from world databases. The default local aliases are `default -> dev_big_control`, `realworld -> dev_big_real` and `simulation0001 -> dev_big_sim0001`. The preferred local shape is three site entrypoints:

```text
http://127.0.0.1:20100/admin/                  # control / bigadmin.local
http://127.0.0.1:20101/workspace/              # real world / bigreal.local
http://127.0.0.1:20101/                              # real world / bigreal.local
http://127.0.0.1:20102/workspace/              # simulation world / bigsim.local
http://127.0.0.1:20102/                              # simulation world / bigsim.local
```

Legacy world-prefixed paths have been removed. Real and simulation development should use the fixed-world site settings and root paths.

## Multi-Database Migration Commands

The default local database layout is:

```text
default        -> dev_big_control
realworld      -> dev_big_real
simulation0001 -> dev_big_sim0001
```

Run migrations for each database alias after creating the physical databases and granting privileges:

```powershell
.\.venv\Scripts\python.exe manage.py migrate --database=default
.\.venv\Scripts\python.exe manage.py migrate --database=realworld
.\.venv\Scripts\python.exe manage.py migrate --database=simulation0001
```

`default` owns `worlds.WorldRegistry` and Django Admin technical accounts. World databases own their own `auth_user`, `django_session` rows and business tables so `bigreal.local` and `bigsim.local` can handle login with their split runtime settings. Under routed admin settings, session reads and writes still use `default`, but `migrate_world` also creates the `django_session` table in each world database. This keeps real and simulation users on the same code path while avoiding cross-world business data mixing.

The optional environment variables are:

```text
BIG_APPLE_CONTROL_DATABASE_URL
BIG_APPLE_REALWORLD_DATABASE_URL
BIG_APPLE_SIMULATION0001_DATABASE_URL
BIG_APPLE_SIMULATION0002_DATABASE_URL
BIG_APPLE_CONTROL_DB_NAME=dev_big_control
BIG_APPLE_REALWORLD_DB_NAME=dev_big_real
BIG_APPLE_SIMULATION0001_DB_NAME=dev_big_sim0001
BIG_APPLE_SIMULATION0002_DB_NAME=dev_big_sim0002
BIG_APPLE_WORLD_DATABASE_ALIASES=realworld,simulation0001,simulation0002
BIG_APPLE_DEFAULT_WORLD_DATABASE_ALIAS=realworld
```

`BIG_APPLE_WORLD_DATABASE_ALIASES` drives Django `DATABASES` entries for world databases. For any alias in that list:

- `BIG_APPLE_{ALIAS}_DATABASE_URL` can fully override the connection URL.
- `BIG_APPLE_{ALIAS}_DB_NAME` can override only the database name while reusing base `DATABASE_URL` credentials and host.
- If no explicit value is provided, simulation aliases such as `simulation0002` default to database names such as `dev_big_sim0002`.

World routing fails closed. When `WORLD_DATABASE_ROUTING_ENABLED=true`, an active `WorldRegistry.database_alias` must be present in `settings.DATABASES`, must be listed in `WORLD_DATABASE_ALIASES`, and must not be `default`. If the alias is missing or points to the control database, requests and ORM routing should fail instead of silently reading or writing control data.

## Repair Missing Admission Proposals

旧数据从单人审核状态机迁移到 proposal-driven admission 后，如果存在历史 `MemberApplication` 有 `linked_member` 但没有 `admission_proposal`，可以对指定 world 运行修复命令。命令一次只修复一个 world 数据库。

```powershell
.\.venv\Scripts\python.exe manage.py repair_member_admission_proposals --world-id realworld --dry-run
.\.venv\Scripts\python.exe manage.py repair_member_admission_proposals --world-id realworld
.\.venv\Scripts\python.exe manage.py repair_member_admission_proposals --world-id simulation0001 --dry-run
```

Docker 开发环境：

```powershell
docker compose -f docker-compose.dev.yml exec -T big-apple-admin python manage.py repair_member_admission_proposals --world-id realworld --dry-run --settings=live_os.settings_admin
docker compose -f docker-compose.dev.yml exec -T big-apple-admin python manage.py repair_member_admission_proposals --world-id realworld --settings=live_os.settings_admin
```

该命令：
- 必须指定 `--world-id`，不能隐式依赖默认 world。
- 只处理 `linked_member` 存在且 `admission_proposal` 为空的 `MemberApplication`。
- 已有 `admission_proposal` 的记录不会被重复创建。
- 没有 `linked_member` 的记录不会被处理。
- `--dry-run` 只输出将修复的记录，不实际写入。
- 查询和提案创建均在指定 world 数据库内完成，不会跨库。

## Repair Formal Member Credentials

扫描拥有 `ROLE_FORMAL_MEMBER` 角色任命但没有正式成员编号凭证的成员，补发 `formal_member_number` Credential Grant。

```powershell
.\.venv\Scripts\python.exe manage.py repair_formal_member_credentials --world-id realworld --dry-run
.\.venv\Scripts\python.exe manage.py repair_formal_member_credentials --world-id realworld
```

该命令：
- 必须指定 `--world-id`。
- `--dry-run` 不写入任何数据（不创建 `CredentialTemplate`，不创建 `CredentialGrant`）。
- 非 dry-run 时才调用 `ensure_builtin_credential_templates()` 和 `issue_formal_member_number()`。
- 已有 `formal_member_number` 凭证的成员不会被重复发放。
- 所有 ORM 读写都在 `command_world_context(world_id)` 内执行，不会写到隐式默认 world。

## Bootstrap First Accounts

三库迁移完成后，可用 `bootstrap_world` 一次性创建：

- control DB 的 Django Admin 技术 root：默认用户名 `admin`，`is_staff=True`，`is_superuser=True`。
- 目标 world DB 的世界治理管理员：默认用户名和成员编号 `member-admin-0001`，`is_staff=False`，`is_superuser=False`，并拥有 `治理管理员` 角色任命和 `governance.*` 基础权限。

推荐用环境变量传入密码，避免把密码写入 shell 历史：

```powershell
$env:BIG_APPLE_CONTROL_ADMIN_PASSWORD="..."
$env:BIG_APPLE_WORLD_ADMIN_PASSWORD="..."
.\.venv\Scripts\python.exe manage.py bootstrap_world --world-id realworld
```

也可以显式传参：

```powershell
.\.venv\Scripts\python.exe manage.py bootstrap_world --world-id realworld --control-password "..." --world-admin-password "..."
```

如果当前 Django 运行在 Docker 开发容器中，使用同一个容器执行命令：

```powershell
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py bootstrap_world --world-id realworld --control-password "..." --world-admin-password "..." --settings=live_os.settings_admin
```

该命令是幂等的；重复执行不会重复创建同一个 `Permission`、`Role`、`Member`、`User` 或 active `RoleAssignment`。control plane 的 `/admin/` 登录使用 control DB 技术账号；固定 world 站点的 `/login/` 登录使用对应 world DB 内的账号。
world 登录成功后统一进入 `/workspace/`。真实世界和仿真世界 runtime 不暴露独立业务后台；需要执行底层维护或高影响操作时，使用 control plane 的 `/admin/`，账号名固定使用 `member_no`。

仿真 world 的首个治理管理员可以通过 `.env` 配置：

```env
BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_ENABLED=true
BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_USERNAME=your-simulation-admin
BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_PASSWORD=CHANGE_ME
BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_EMAIL=
BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_MEMBER_NO=your-simulation-admin
BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_DISPLAY_NAME=Simulation admin
```

只有显式启用并同时提供用户名和密码时，`seed_world` 每次成功初始化目标仿真 world 后才会确保该账号存在并拥有治理管理员角色。`BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_PASSWORD=CHANGE_ME` 是模板占位符，启用前必须改掉，否则命令会失败。这样重置 `simulation0001` 对应数据库后，再运行 `seed_world simulation0001 --template ...`，即可继续使用该账号登录 `bigsim.local/workspace/`。

## World Lifecycle Commands

世界生命周期由 control DB 的 `worlds.WorldRegistry` 管理。当前命令只管理 world 登记和状态，不自动创建或删除 MySQL 物理数据库；物理数据库仍应由技术管理员先创建、授权，再把 alias 加入 Django settings。

新增仿真世界的闭环：

1. 在 MySQL 中创建物理数据库，例如 `dev_big_sim0002`，并给当前 Django 数据库账号授权。
2. 在 `.env` 中把 alias 加入 `BIG_APPLE_WORLD_DATABASE_ALIASES=realworld,simulation0001,simulation0002`。如数据库名不符合默认推导，再设置 `BIG_APPLE_SIMULATION0002_DB_NAME` 或 `BIG_APPLE_SIMULATION0002_DATABASE_URL`。
3. 重启 Django 进程，让新的 alias 进入 `settings.DATABASES`。
4. 用 `create_world` 登记 world。
5. 用 `migrate_world` 初始化该 world 数据库结构。
6. 用 `bootstrap_world --world-id simulation0002` 创建该仿真 world 的首个治理管理员。
7. 如需后台预览数据，用 `seed_world simulation0002 --template demo` 初始化仿真 world；如需真正从一个发起人开始推演，用 `seed_world simulation0002 --template zero_start`。

登记一个已配置数据库 alias 的仿真世界：

```powershell
.\.venv\Scripts\python.exe manage.py create_world simulation0002 --name "Simulation 0002"
```

对某个 active world 运行迁移：

```powershell
.\.venv\Scripts\python.exe manage.py migrate_world simulation0002 --noinput
```

用安全模板初始化仿真世界：

```powershell
.\.venv\Scripts\python.exe manage.py seed_world simulation0002 --template demo
.\.venv\Scripts\python.exe manage.py seed_world simulation0002 --template zero_start
```

`seed_world` 只允许作用于 `world_type=simulation` 的 active world。`demo` 模板复用现有幂等 `seed_demo` 数据，用于后台预览；`zero_start` 模板只创建一个发起人和极简计划，用于从真正零起点推演自媒体报名、成员筛选和启动门槛确认。启用仿真 bootstrap admin 时，发起人使用该真实登录成员；未启用时使用非交互 fallback 发起人。两个模板都不会复制 `realworld` 数据，也不会清空、归档或删除任何物理数据库。

### 通过后台重置仿真世界

除了命令行 `seed_world`，还可以通过仿真实验后台直接重置一个仿真世界到 zero_start 基线：

1. 以 superuser 身份登录 `http://bigadmin.local/admin/simulation-lab/?world_id=simulation0001`。
2. 在"重置仿真世界"模块中：
   - 输入当前 world_id（例如 `simulation0001`）确认。
   - 输入确认文字"确认重置"。
   - 如果存在运行中或已结束但未处置的 run，勾选"强制重置"。
3. 点击"重置到零起点基线"。
4. 成功后目标 world 只有 zero_start 基线数据，不会推进虚拟小时，不会创建 SimulationRun / SimulationTurn。

与 `run_zero_start_simulation` 的区别：重置只清空并 seed 基线；`run_zero_start_simulation` 才创建 `SimulationRun` / `SimulationTurn` 并推进虚拟小时。重置后的审计记录写入 control DB 的 `WorldMaintenanceLog`（在 `/admin/worlds/worldmaintenancelog/` 中只读查看）。

通过后台重置与命令行 `seed_world simulation0001 --template zero_start` 功能等价，但命令不执行 flush（不先清空已有数据），需手动先运行 `python manage.py flush --database=simulation0001 --noinput`。后台重置页面会把清空和重新 seed 串成一次受控维护流程；如果 seed 失败，会写入失败审计记录，需要修复配置后重新执行。

不要手动对本地 `dev_big_sim0001` 数据库执行 `flush`；日常开发测试使用后台页面重置或命令行 `seed_world` 覆盖即可。

After a simulation world is archived, it no longer participates in normal login or fixed-site world binding:

```powershell
.\.venv\Scripts\python.exe manage.py archive_world simulation0002
```

删除仿真世界登记。删除前必须先归档；命令只把 registry 标记为 `deleted`，不会 drop database：

```powershell
.\.venv\Scripts\python.exe manage.py delete_world simulation0002
```

`realworld` 和 `world_type=real` 的世界不能被 `archive_world` 或 `delete_world` 操作。新增 world 的 `database_alias` 必须已经存在于 `settings.DATABASES`，并列入 `BIG_APPLE_WORLD_DATABASE_ALIASES`。
