## Why

Workspace 现有功能入口仍以密集的小按钮和大块分组容器呈现，与已确定的竖版应用式设计语言差异明显，入口层级也不够清楚。需要在不改变任何真实功能、权限或顺序的前提下，把这些入口逐步改造成更易识别和点击的快捷操作卡片。

## What Changes

- 在 Workspace 欢迎与状态区域之后增加明确的“快捷操作”视觉区段。
- 将现有入口按原有分组、顺序和权限条件改为三列图标卡片网格。
- 复用仓库现有的本地 Lucide 图标资源；图标只辅助识别，文字仍是完整的可访问名称。
- 保留所有现有 Workspace 功能入口，不新增设计稿中的虚构入口，也不删除或迁移任何入口。
- 保留“我的事务”及其后续现有模块，本次只改功能导航的视觉呈现。
- 非目标：不实现底部导航，不修改业务流程、URL、服务器端上下文、授权规则或数据模型。
- 权限影响：无。入口可见性继续使用现有模板权限条件。
- 数据影响：无。不新增或迁移数据。
- 公开契约影响：无。不修改 API、schema 或 payload。

## Capabilities

### New Capabilities

- `workspace-quick-actions`: 规定 Workspace 真实功能入口的卡片式展示、分组、顺序、权限保留和可访问性。

### Modified Capabilities

无。

## Impact

- 修改 `templates/workspace/index.html` 中现有导航区的结构和样式类。
- 复用 `theme/static/js/dist/lucide.min.js`，不引入新依赖或外部 CDN。
- 更新 Workspace 页面测试、编译后的 Tailwind CSS 和成员 Workspace 产品文档。
- 不修改数据库、领域服务、API、URL 名称或权限判断。
