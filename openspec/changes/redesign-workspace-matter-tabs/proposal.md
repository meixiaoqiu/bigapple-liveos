## Why

Workspace 的“我的事务”仍以一张厚重大卡片同时纵向展示三个分组，空数据时也占据大量页面高度，与已经建立的紧凑竖版应用布局不一致。需要在不改变事务投影事实和权限边界的前提下，将它收敛为更清楚的标签页和紧凑事务卡片。

## What Changes

- 将“我的事务”从重阴影大卡片改为轻量独立区段，保留标题、说明和进行中总数。
- 将“需要我处理”“等待他人”“最近结束”改为三个带数量的标签页，默认显示“需要我处理”，每次只突出显示一个分组。
- 保留三个现有事务分组，不因参考设计稿只画出两个标签而删除“等待他人”。
- 将事务条目改为紧凑的白色描边卡片，完整保留类型、状态、标题、稳定 ID、责任、当前处理方、下一步、更新时间和详情入口。
- 将无数据分组收敛为轻量单行空状态，将迁移期说明改为轻量描边提示。
- 为标签页提供键盘和辅助技术可识别的语义；脚本不可用时三个分组内容仍可阅读和访问。
- 保留“我的事务”之后的所有现有 Workspace 模块，不删除、迁移或重排它们。
- 为 Workspace 首页引入接近设计稿黑白配色的 `bigapple` 主题（黑色主色、白色背景、浅灰描边），并把首页 `data-theme` 从 `bumblebee` 切换为该主题，使选中标签下划线等主色元素无需逐模块单独写颜色。其他 Workspace 页面继续使用 `bumblebee`，不在本轮统一替换。
- 非目标：不修改事务来源、分组规则、排序、数量上限、责任事实、权限判断、目标 URL 或任何领域状态机；不增加新的写操作、API 或底部导航；不把全站其他 Workspace 页面统一切换到 `bigapple` 主题。
- 权限影响：无。详情入口继续服从现有目标页面权限，标签页不授予任何业务权限。
- 数据影响：无。不修改模型、数据库、查询投影或迁移。
- 公开契约影响：无。不修改 API、schema 或 payload。

## Capabilities

### New Capabilities

- `workspace-matter-tabs`: 规定 Workspace 事务分组的标签页交互、紧凑卡片、渐进增强、可访问性和现有事务事实保留规则。

### Modified Capabilities

无。

## Impact

- 修改 `templates/workspace/index.html` 中“我的事务”区段、`templates/workspace/partials/matter_group.html`，以及首页 `data-theme`。
- 在 `theme/static_src/src/styles.css` 中新增 `bigapple` 主题并加入 daisyUI themes 列表。
- 增加少量页面内标签页渐进增强逻辑，不引入新前端依赖。
- 更新 Workspace 页面测试、Tailwind 编译产物和 sibling 成员 Workspace 产品文档。
- 不修改 `workspace/work_item_context.py`、view、领域服务、模型、URL 或技术契约。
