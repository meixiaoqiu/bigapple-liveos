# 远程开发环境说明

本文档只描述可公开的远程开发约定，不记录个人服务器名、私有域名、内网 IP 或生产资源路径。

## 运行用户

远程开发建议使用独立的非 root 用户。用户名称由部署者自行决定，不应写入仓库文档。

## Docker

远程开发建议使用该非 root 用户的 rootless Docker。

不要使用宿主机 root Docker。宿主机 root Docker 通常留给生产部署平台或其他正式服务使用。

不要访问或修改生产环境路径和资源，包括：

- 生产部署平台目录
- 生产 Docker volume
- 生产容器
- 生产数据库
- 生产 `.env` 文件

## 环境变量

远程开发环境变量文件是 `.env.dev`。

`.env.dev` 被 Git 忽略，不能提交。

常用占位配置：

```env
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,你的远程开发域名
DJANGO_CSRF_TRUSTED_ORIGINS=https://你的远程开发域名:20101
REMOTE_DEV_PUBLIC_URL=https://你的远程开发域名:20101/
REMOTE_DEV_MYSQL_HOST=mysql
REMOTE_DEV_MYSQL_PORT=3306
```

如果通过 Tailscale、VPN 或内网代理访问，请把实际域名和 IP 只写入 `.env.dev` 或服务器本地 shell 环境，不要写入仓库。

## 常用脚本

- `./remote-start-dev.sh`
- `./remote-stop-dev.sh`
- `./remote-logs-dev.sh`
- `./remote-check-dev.sh`

## Compose 文件

`docker-compose.remote-dev.yml`

## 端口

远程开发 Web 端口默认是 `20101`。

## 访问地址

本机或 SSH 转发访问：

```text
http://127.0.0.1:20101/
```

远程公开或 VPN 访问地址通过 `REMOTE_DEV_PUBLIC_URL` 配置。

## 数据库

远程开发只能连接 dev 专用数据库，不连接生产库。

当前 world 数据库别名：

- `default`
- `realworld`
- `simulation0001`

## 检查命令

```bash
./remote-check-dev.sh
```
