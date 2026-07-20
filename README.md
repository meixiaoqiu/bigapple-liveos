# big-apple-live-os

`big-apple-live-os` 是“大苹果”v0.1 的权威生活系统。

它实现相邻仓库 `big-apple-contracts` 中定义的契约。Simulation Engine 必须像真实成员一样通过 Live OS API 使用系统，不能直接写入 Live OS 的业务数据表。

## 当前阶段

第一阶段已经建立了一个文档先行的 Django 原型，覆盖：

- 成员身份
- 任务系统
- 贡献积分账本
- 资源状态
- 事件流
- 申诉记录
- 规则版本
- 容量评估
- 观察台摘要 API
- 观察台页面
- Tailwind、daisyUI、HTMX 版观察台前端
- 数据库化项目执行计划
- 自动模拟跑到失败和计划修订建议
- 计划修订建议转结构化数据 patch

规划口径按照中远期完全体描述，当前实现刻意保持小而清晰：先把表结构、API 边界、契约映射和开发规则写清楚，再继续扩展功能。

## 仓库关系

推荐本地目录结构：

```text
big-apple/
├── big-apple-contracts/
└── big-apple-live-os/
```

这两个目录都是独立 Git 仓库。

## 数据库

本地开发当前使用 MySQL，并通过 Docker compose 启动三个 Django 站点服务：`big-apple-admin`、`big-apple-real`、`big-apple-sim`。请从示例文件复制本地 env 文件并填写连接信息：

```text
.env
```

格式：

```dotenv
DATABASE_URL=mysql://用户名:URL编码后的密码@mysql97:3306/数据库名?charset=utf8mb4
```

Docker 开发模式下，Web 容器和 MySQL 容器通过 `dev-net` 通信，所以 `.env` 里的 MySQL host 应写容器名 `mysql97`，不是宿主机的 `127.0.0.1`。真实连接文件已被 `.gitignore` 忽略。

`start.bat` 会检查 Docker Desktop、`dev-net` 网络、已有 `mysql97` 容器和已有 `nginx` 容器；它会启动已存在的容器并把它们接入 `dev-net`，但不会创建数据库容器、nginx 容器或 Docker network。

## 安装

```bat
copy .env.example .env
notepad .env
start.bat
```

首次启动后，在另一个终端执行 control DB 迁移、world DB 迁移和演示数据初始化：

```bat
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py migrate --settings=live_os.settings_admin
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py migrate_world realworld --noinput --settings=live_os.settings_admin
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py migrate_world simulation0001 --noinput --settings=live_os.settings_admin
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py seed_demo --world-id realworld --settings=live_os.settings_admin
```

`start.bat` 会通过 Docker compose 启动三个站点：control 后台在 `127.0.0.1:20100`，真实世界在 `127.0.0.1:20101`，仿真世界在 `127.0.0.1:20102`，并启动本地 nginx gateway。停止 Django 容器可以运行：

```bat
docker compose -f docker-compose.dev.yml down
```

当前仓库已经提供不依赖第三方包的检查脚本。默认只检查 Live OS 仓库自身，不要求相邻 `big-apple-contracts` 仓库存在：

```bash
python scripts/check_project.py
```

涉及 API、schema 或 payload 兼容性时，再显式检查 contracts：

```bash
python scripts/check_project.py --check-contracts
```

## 管理后台

当前已经拆成三个站点入口，可以在运行服务后访问：

```text
http://127.0.0.1:20100/admin/
http://127.0.0.1:20100/admin/simulation-lab/
http://127.0.0.1:20101/workspace/
http://127.0.0.1:20101/observer/
http://127.0.0.1:20102/workspace/
http://127.0.0.1:20102/observer/
```

`bigadmin.local` / `127.0.0.1:20100` 是唯一 Django Admin / control plane：负责技术后台、底层数据管理、仿真实验后台、世界注册表、仿真归档和兜底维护。`bigreal.local` / `127.0.0.1:20101` 是真实世界 runtime。`bigsim.local` / `127.0.0.1:20102` 是仿真世界 runtime。真实和仿真 runtime 不暴露 `/admin/`，也不再暴露 `/live-admin/`；世界站点只保留 `/workspace/`、`/observer/`、报名入口和 API。

Admin 当前的模型用途和保护规则见 `../bigapple-docs/docs/product/admin.md`。

成员工作台最小页面可以访问：

```text
http://127.0.0.1:20101/workspace/
```

运营后台页面可以访问：

```text
http://127.0.0.1:20100/admin/
http://127.0.0.1:20100/admin/simulation-lab/
```

底层、危险或会造成严重后果的操作统一进入 control 后台；世界站点不再提供独立运营后台。

观察台可以访问：

```text
http://127.0.0.1:20101/observer/
```

当前 `bigreal.local/observer/` / `127.0.0.1:20101/observer/` 是真实世界时间线指挥台式总览，使用 Django Templates、Tailwind、daisyUI 和 HTMX。首页展示今日事件时间线、核心指标、风险侧栏、容量评估、高负载岗位和待处理争议；任务、资源、成员和数据日志下沉到二级入口。

观察台相关前端资源由 `django-tailwind` 管理，源码在 `theme/static_src/`，编译产物在 `theme/static/css/dist/styles.css`。当前 Dockerfile 不安装 Node.js；修改观察台模板或 Tailwind class 后，需要在宿主机 Python/Node 开发环境中运行：

```bash
python manage.py tailwind build
```

自动模拟仍保留原 POST 动作：系统会基于 `bigapple001据点执行计划` 创建一次模拟运行，按主线节点推进，直到预算、人力、技能、资源、依赖或人员状态触发失败，并生成待审核的计划修订建议以及结构化计划数据 patch。详细说明见 `../bigapple-docs/docs/product/simulation.md` 和 `../bigapple-docs/docs/product/project-plan.md`。

要登录 Django Admin，需要先创建超级用户：

```bat
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py createsuperuser --settings=live_os.settings_admin
```

写入演示数据：

```bat
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py seed_demo --world-id realworld --settings=live_os.settings_admin
```

`seed_demo` 是幂等命令，会用固定业务 ID 更新或创建演示数据，不会清空数据库。运行时启用 world 数据库路由后，直接执行必须显式传入 `--world-id`。执行后，后台可以看到成员、任务、资源、事件、积分流水、申诉、容量评估和 `bigapple001据点执行计划`。

跑通第一条 API 业务闭环：

```bat
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py smoke_workflow --world-id realworld --seed-demo --settings=live_os.settings_admin
```

`smoke_workflow` 会通过 Live OS HTTP API 完成“查询开放任务 -> 领取任务 -> 提交劳动 -> 验收任务 -> 生成积分流水和事件 -> 查询观察台摘要”。真实世界默认不会写入演示数据；如需本地演示验证，显式传入 `--seed-demo`，或先单独运行 `seed_demo --world-id realworld`。仿真 world 使用 `--world-id simulation0001` 时会自动调用 `seed_world` 准备幂等演示起点。它会在目标 world 数据库中新建一个 `task-smoke-*` 任务，用于验证系统没有坏。

如果后台没有样式，或仍显示英文标题 `Django administration`，请停止旧容器后重新启动：

```powershell
docker compose -f docker-compose.dev.yml down
start.bat
```

## 文档

- 已迁移到 `../bigapple-docs/docs/architecture/overview.md`
- 已迁移到 `../bigapple-docs/docs/project/product-planning.md`
- 已迁移到 `../bigapple-docs/docs/project/roadmap.md`
- 已迁移到 `../bigapple-docs/docs/product/admin.md`
- 已迁移到 `../bigapple-docs/docs/architecture/database-schema.md`
- 已迁移到 `../bigapple-docs/docs/reference/api.md`
- 已迁移到 `../bigapple-docs/docs/product/observer.md`
- 已迁移到 `../bigapple-docs/docs/product/simulation.md`
- 已迁移到 `../bigapple-docs/docs/product/project-plan.md`
- 已迁移到 `../bigapple-docs/docs/product/member-workspace.md`
- 已迁移到 `../bigapple-docs/docs/operations/runtime-boundary.md`
- 已迁移到 `../bigapple-docs/docs/development/setup.md`
- 已迁移到 `../bigapple-docs/docs/operations/mysql-migration.md`
- 已迁移到 `../bigapple-docs/docs/development/ai-guide.md`
- 已迁移到 `../bigapple-docs/docs/development/theme-system.md`
- 已迁移到 `../bigapple-docs/docs/development/remote-dev.md`

## 参与和治理

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [GOVERNANCE.md](GOVERNANCE.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- [SECURITY.md](SECURITY.md)

## 开源协议

`big-apple-live-os` 的项目自有代码和文档按 `AGPL-3.0-or-later` 发布，完整许可证正文见 [LICENSE](LICENSE)，第三方声明见 [NOTICE](NOTICE)。

如果修改本项目后通过网络向用户提供服务，需要按 AGPL 的网络交互条款向用户提供对应源码。

## 契约规则

API 和数据结构变更必须先进入 `big-apple-contracts`。Live OS 再实现这些契约，并通过测试证明 API 响应符合 schema。

## 测试

API 闭环测试使用独立测试设置，默认走 SQLite 内存库，避免依赖本地 MySQL 连接：

```bat
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py test core live_os observer workspace simulation simulation_lab worlds --settings=live_os.test_settings
```
