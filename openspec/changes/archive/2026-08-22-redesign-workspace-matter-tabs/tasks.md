## 1. 事务区段与标签页

- [x] 1.1 将“我的事务”改为轻量独立区段，保留标题、说明、进行中总数及其在快捷操作和后续旧模块之间的现有位置
- [x] 1.2 为“需要我处理”“等待他人”“最近结束”建立按原顺序排列且带实际列表数量的标签和关联面板，默认增强为“需要我处理”
- [x] 1.3 实现无外部依赖的渐进增强脚本，支持点击、ArrowLeft、ArrowRight、Home、End、焦点同步及 `aria-selected`、`tabindex`、`hidden` 同步；确认无脚本时三个面板全部可读
- [x] 1.4 标签控制条初始带 `hidden`，增强脚本初始化成功后移除 `hidden` 并激活第一项、隐藏其余面板，避免无脚本时出现不可操作的标签按钮

## 2. 紧凑事务内容

- [x] 2.1 重构 `matter_group.html` 为轻量面板和白色描边事务卡片，完整保留类型、状态、标题、稳定 ID、责任、当前处理、下一步、更新时间和原目标 URL
- [x] 2.2 行动分组使用“进入处理”，等待与结束分组使用“查看详情”，且没有 `target_url` 的事务不渲染虚构按钮
- [x] 2.3 将零事项分组改为轻量单行空状态，将迁移期说明改为轻量描边提示，不改变文案语义

## 3. 首页主题

- [x] 3.1 在 `theme/static_src/src/styles.css` 定义接近设计稿黑白配色的 `bigapple` 主题并加入 daisyUI themes 列表
- [x] 3.2 将 Workspace 首页 `data-theme` 从 `bumblebee` 切换为 `bigapple`，使选中标签下划线等主色元素无需逐模块写颜色；其他 Workspace 页面保持 `bumblebee`

## 4. 回归覆盖与文档

- [x] 4.1 更新 Workspace 页面测试，验证三个标签的顺序、数量、ARIA 关联、默认标签标记、控制条初始 `hidden`、面板初始无 `hidden` 和无脚本内容完整性
- [x] 4.2 扩展事务卡片回归测试，验证三组现有事项身份、顺序、面板归属、全部事务事实、目标 URL、无 `target_url` 不生成按钮、空状态及“我的事务”之后的旧模块均保持不变
- [x] 4.3 更新 `bigapple-docs/docs/product/member-workspace.md`，记录三标签、渐进增强、紧凑卡片、首页 `bigapple` 主题及事务投影边界

## 5. 构建与验证

- [x] 5.1 运行 Tailwind build（`npm run build:tailwind`，含 `--minify`）并提交更新后的 `theme/static/css/dist/styles.css`，确认没有意外改写 Lucide 生成资源版本
- [x] 5.2 在有事务和全空数据下人工检查窄屏与宽屏，验证标签切换、键盘操作、长文本换行、空状态高度和无横向溢出
- [x] 5.3 运行 Workspace 定向测试、项目检查、Django check、迁移漂移检查、相关 OpenSpec strict validation 及两个仓库的 `git diff --check`
- [x] 5.4 审查最终 diff，确认未修改 `workspace/work_item_context.py`、view、模型、领域服务、URL、权限判断或技术契约
