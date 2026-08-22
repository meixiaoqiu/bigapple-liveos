## Why

Workspace 主体已经采用 480px 竖版应用布局，但首页仍嵌入面向宽屏网站的横向公共导航，七个入口在窄画布中拥挤，并破坏顶部应用栏的视觉层级。需要为 Workspace 首页提供专用紧凑页头，同时完整保留现有运行时导航能力。

## What Changes

- 仅在已登录成员的 Workspace 首页使用紧凑应用页头，不修改全站共享的 `runtime_header.html` 及其他页面。
- 页头左侧保留现有社区品牌文字和首页目标地址，右侧改为一个有明确可访问名称的菜单入口。
- 菜单展开后按 `runtime_nav.items` 的现有顺序显示“首页、事件流、财务、资源库存、我的主页、工作台、退出”等实际可见入口。
- 保留每个入口的现有 URL 和 GET/POST 方法；“退出”继续使用带 CSRF 的 POST 表单，不得降级为 GET 链接。
- 使用原生可渐进工作的菜单结构，键盘和无脚本环境均可打开、浏览和关闭。
- 不添加尚不存在的通知铃铛、未读数量、头像操作、底部导航或新功能入口。
- 保留 480px 连续白色画布及当前欢迎、状态摘要、快捷操作、我的事务和后续模块。
- 非目标：不重新设计其他 Workspace 子页面、Observer、财务页、事件页或公共运行时页头；不修改 `runtime_nav` 的构建规则。
- 权限影响：无。页头只消费现有 `runtime_nav`，不增加、推断或绕过权限。
- 数据影响：无。不修改模型、数据库、查询或迁移。
- 公开契约影响：无。不修改 API、schema 或 payload。

## Capabilities

### New Capabilities

- `workspace-compact-header`: 规定 Workspace 首页专用紧凑页头、完整导航菜单、方法安全、可访问性和作用范围。

### Modified Capabilities

无。

## Impact

- 新增 Workspace 首页专用页头 partial，并修改 `templates/workspace/index.html` 的 include。
- 复用现有 `runtime_nav` 上下文和本地 Lucide 资源，不新增依赖或服务器端上下文。
- 更新 Workspace 页面测试、Tailwind 编译产物和 sibling 成员 Workspace 产品文档。
- `templates/partials/runtime_header.html` 及其所有其他调用页面保持不变。
