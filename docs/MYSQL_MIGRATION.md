# MySQL 接入、数据导入与切换手册

## 当前状态

- PostgreSQL 本地数据已经不可用，正常运行入口切换为 MySQL。
- 项目配置支持从 `DATABASE_URL` 环境变量或根目录 `.env` 读取 `mysql://` 连接。
- `start.bat` 不再静默回退 PostgreSQL；缺少 MySQL 连接或 Docker 开发前提不满足时会直接停止并提示原因。
- 当前切换只改数据库连接配置、脚本和文档，不修改数据库模型，不创建 MySQL 专属迁移。

## 运行要求

目标数据库必须满足：

- MySQL 8.0 或更高版本。
- InnoDB 存储引擎。
- `utf8mb4` 字符集。
- 大小写敏感排序规则，推荐 `utf8mb4_0900_as_cs`。
- `STRICT_TRANS_TABLES` 或 `STRICT_ALL_TABLES` SQL 模式。
- `READ-COMMITTED` 事务隔离级别。
- 支持事务、`SELECT FOR UPDATE` 和原生 JSON。

大小写敏感排序规则是必要条件。项目大量使用字符串业务 ID 作为主键，
如果使用 MySQL 常见的大小写不敏感排序规则，`member-a` 和 `MEMBER-A`
可能被当作相同 ID，与当前 PostgreSQL 语义不一致。

## 连接信息填写位置

请编辑本地 env 文件：

```text
.env
```

填写格式：

```dotenv
DATABASE_URL=mysql://用户名:URL编码后的密码@mysql97:3306/数据库名?charset=utf8mb4
```

示例：

```dotenv
DATABASE_URL=mysql://big_apple_user:your_password@mysql97:3306/big_apple_live?charset=utf8mb4
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,bigadmin.local,bigreal.local,bigsim.local
```

Docker 开发模式下，`big-apple-admin`、`big-apple-real`、`big-apple-sim` 和 `mysql97` 运行在同一个 `dev-net` 网络中，所以连接字符串必须使用容器名 `mysql97`。如果在容器内使用 `127.0.0.1`，Django 会连接到 Web 容器自己。

用户名、密码和数据库名中的 `@`、`:`、`/`、`#`、`?`、`%` 等保留字符
必须进行 URL 编码。该文件已被 `.gitignore` 忽略，禁止提交真实凭据。

当前 `start.bat` 会读取根目录 `.env`。读取到的连接必须是 `mysql://`，且 Docker 开发模式下 host 必须是 `mysql97`，否则启动会失败。

## 推荐建库方式

以下 SQL 需要由有权限的 MySQL 管理员根据实际用户名和密码执行：

```sql
CREATE DATABASE big_apple_live
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_as_cs;

CREATE USER 'big_apple_user'@'127.0.0.1'
  IDENTIFIED BY 'replace-with-a-strong-password';

GRANT ALL PRIVILEGES ON big_apple_live.* TO 'big_apple_user'@'127.0.0.1';
FLUSH PRIVILEGES;
```

生产环境应进一步收紧权限。迁移阶段需要建表、修改表和写入数据权限。

## 安装 MySQL 驱动

Dockerfile 会在 Big Apple Django 开发镜像中安装 Django 官方推荐的 `mysqlclient`。如果需要在宿主机 `.venv` 中运行旧的辅助脚本，可手动安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,mysql]"
```

## 填写连接信息后的就绪检查

```powershell
docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py check_mysql_readiness --settings=live_os.settings_admin
```

该命令会使用 compose 传入容器的 `.env`。
它会检查版本、存储引擎、字符集、排序规则、严格模式、事务隔离级别、
JSONField 和行锁能力。

## 数据导入阶段

连接信息和就绪检查通过后，按以下顺序执行。由于 PostgreSQL 数据已经丢失，
本次只导入表结构并初始化必要数据，不再执行 PostgreSQL 数据迁移。

1. 确认 MySQL 数据库为空库，或确认可以覆盖当前表结构。
2. 使用 MySQL 配置执行迁移建表：

   ```powershell
   docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py migrate --settings=live_os.settings_admin
   docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py migrate_world realworld --noinput --settings=live_os.settings_admin
   docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py migrate_world simulation0001 --noinput --settings=live_os.settings_admin
   ```

3. 初始化演示/基础数据：

   ```powershell
   docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py seed_demo --world-id realworld --settings=live_os.settings_admin
   ```

4. 再次执行：

   ```powershell
   docker compose -f docker-compose.dev.yml exec big-apple-admin python manage.py check_mysql_readiness --settings=live_os.settings_admin
   ```

5. 在 MySQL 上运行 Django 检查、测试、seed 幂等检查和核心业务冒烟流程。

导出和导入文件不得提交到 Git，并应放入受控的临时目录。

## 正式运行

填写根目录 `.env` 并完成建表后，可以直接使用：

```bat
start.bat
```

启动脚本不会输出包含密码的 `DATABASE_URL`。它会检查已有 `dev-net`、`mysql97` 和 `nginx`，启动已存在的容器并连接网络，但不会创建数据库容器、nginx 容器、Docker network 或数据卷。

## 回滚

PostgreSQL 数据已经丢失，当前没有可自动回滚的旧数据库。若 MySQL 验收失败：

1. 停止服务写入。
2. 修正 MySQL 建库参数、连接权限或迁移问题。
3. 重新执行 `migrate`、`seed_demo --world-id realworld`、就绪检查和功能测试。
4. 如需保留失败现场，先备份当前 MySQL 库，再清库重建。

## 已知兼容性关注点

- `JSONField` 在 MySQL 8 可用，但 JSON 查询执行计划和索引能力与 PostgreSQL 不同。
- `select_for_update()` 依赖 InnoDB 和事务配置。
- MySQL 与 PostgreSQL 对 NULL 默认排序位置不同，部分任务列表顺序可能变化。
- 积分流水不再维护独立 `immutable_sequence`；全局审计顺序统一来自 `core_system_event.seq`。
  并发关注点集中在 `core.event_ledger.append_event()` 的事务和 `select_for_update()` 链尾读取。
