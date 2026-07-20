# 贡献指南

感谢你帮助改进 Big Apple Live OS。

## 仓库边界

- 契约、schema 或 payload 变更必须先进入 `../bigapple-docs/technical-contracts`。
- Runtime 行为、Django views、models、migrations、templates 和本仓库文档属于 `big-apple-live-os`。
- 生成缓存、本地 `.env`、数据库导出、生产日志和 `output/` 产物不得提交。

## 文档语言

除许可证正文、标准协议名称、代码标识、命令、配置键、API 路径和必要的第三方名称外，项目文档默认使用中文。

## 本地检查

提交 pull request 前，请至少运行：

```bash
python scripts/check_project.py
python manage.py test core live_os observer workspace simulation simulation_lab worlds --settings=live_os.test_settings
```

如果修改了 `theme/static_src/` 下的前端源码，还需要运行：

```bash
cd theme/static_src
npm ci
npm run build
```

## Pull Request 要求

- 每个 PR 尽量只覆盖一个行为、修复或文档主题。
- 修改 runtime 行为时必须新增或更新测试。
- 不要包含凭据、私有数据、本机绝对路径、生成缓存或无关格式化改动。
- 如果涉及契约变更，请说明对应的 `../bigapple-docs/technical-contracts/` 变更；本仓库不得单方面改变已发布契约。
- 说明实际运行过的验证命令；如果只运行了局部测试，也要明确说明。

## 贡献授权

向本仓库提交代码、文档或其他项目自有内容，即表示你同意这些贡献按 `AGPL-3.0-or-later` 授权发布，除非单个文件另有明确说明。
