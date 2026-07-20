# 项目治理

本文件只适用于 `big-apple-live-os` 仓库。技术契约位于相邻 `bigapple-docs` 仓库的 `technical-contracts/` 目录，契约、schema 和 payload 的治理规则以该仓库后续文件为准。

## 维护范围

`big-apple-live-os` 负责 Big Apple Live OS 的 runtime 实现、Django 应用、迁移、模板、前端源码、本仓库文档和本地开发脚本。

契约、schema、跨仓库 payload 和对外 API 语义变更必须先在 `../bigapple-docs/technical-contracts` 中完成，再由本仓库实现和验证。

## 角色

- 仓库所有者负责仓库权限、发布策略、安全响应、许可证和最终争议处理。
- 维护者负责 issue triage、代码审查、合并决策、回归风险判断和发布前检查。
- 贡献者通过 issue、讨论、文档、测试或 pull request 参与项目。

当前项目处于早期原型阶段，维护者名单和发布节奏可能随项目成熟度调整。

## 决策原则

- 安全、许可证、隐私、公开发布边界和契约兼容性优先于功能速度。
- 行为变更需要测试或可复现验证支撑。
- 文档默认使用中文；许可证正文、标准协议名称、代码标识、命令、配置键和必要第三方名称保留原文。
- 不提交 `.env`、token、成员数据、数据库导出、生产日志、生成缓存或本机绝对路径。

## 合并要求

PR 合并前应满足：

- 变更范围清晰，且没有混入无关格式化或缓存文件。
- 相关测试、检查脚本或手动验证结果已经写入 PR。
- Runtime 行为变更有对应测试或说明无法自动化验证的原因。
- 契约变更已在 `../bigapple-docs/technical-contracts` 中处理，或明确说明本 PR 不改变契约。
- 安全敏感变更已按 [SECURITY.md](SECURITY.md) 私有处理流程审查。

## 发布口径

在正式版本标签出现前，本项目不承诺稳定 API、数据库 schema 或部署兼容性。公开发布前必须再次检查许可证、第三方声明、敏感信息、生成产物、测试状态和 README 中的运行说明。

## 行为和争议

协作行为遵循 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。安全问题遵循 [SECURITY.md](SECURITY.md)。维护者会优先用可验证证据和项目边界处理争议。
