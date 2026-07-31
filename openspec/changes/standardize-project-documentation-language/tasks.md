## 1. 固化项目规则

- [x] 1.1 更新 `openspec/config.yaml`，为 proposal、spec、design、tasks、apply 和 archive 注入中文文档上下文与产物规则。
- [x] 1.2 修订当前 `optimize-role-permission-model` 变更，除结构关键字、代码与必要专业术语外全部使用中文。
- [x] 1.3 将 `project-documentation-language` delta spec 同步到 OpenSpec 主规格，并验证主规格不包含 delta 操作标题。
- [ ] 1.4 在 sibling 文档仓库的 AI 开发指南中记录相同语言边界及允许保留原文的内容。

## 2. 确定性语言检查

- [ ] 2.1 实现只读 Markdown 语言检查器，区分标题、普通段落、列表、表格、代码块、行内代码、链接和路径。
- [ ] 2.2 增加仓库内专业术语与 OpenSpec 结构关键字例外，任何文件级或行级忽略都必须包含理由。
- [ ] 2.3 增加测试，覆盖普通英文标题、英文段落、英文任务说明、合法代码标识、命令、路径、API、schema、payload 和混合中文技术说明。
- [ ] 2.4 将语言检查接入 `scripts/check_project.py`，并保证对相同文件状态重复运行得到相同结果。

## 3. 历史文档盘点与清理

- [ ] 3.1 以 JSON 和人类可读格式盘点 Live OS 与 sibling 文档仓库中的普通英文说明，报告文件、位置、分类与建议处理方式。
- [x] 3.2 清理 active OpenSpec 变更和主规格中的普通英文说明，并保持 OpenSpec 严格校验通过。
- [ ] 3.3 按文档所有权分批清理其余历史英文说明，不翻译代码标识、技术契约字段或会改变语义的专业术语。
- [ ] 3.4 历史基线清零后移除临时豁免，使完整文档范围执行严格检查。

## 4. 验证

- [x] 4.1 运行两个 active OpenSpec 变更的严格校验，确认所有产物完整且可解析。
- [ ] 4.2 运行文档语言检查器的单元测试和项目检查，记录 PASS、FAIL、SKIP 结果及剩余例外。
- [x] 4.3 运行 `git diff --check`，确认文档和配置不存在格式错误。
