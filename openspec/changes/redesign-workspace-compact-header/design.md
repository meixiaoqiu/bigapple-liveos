## Context

参见 `proposal.md`。当前 `templates/partials/runtime_header.html` 被大量 Runtime、Observer 和 Workspace 页面共享，它把 `runtime_nav.items` 横向铺在品牌右侧。Workspace 首页已经将这个公共 partial 放入 480px 白色画布，因此七个已登录导航项与品牌争夺同一行空间；直接修改共享 partial 会扩大到所有调用页面。

## Goals / Non-Goals

**Goals:**

- 只替换 Workspace 首页的页头 include，保持共享 partial 零改动。
- 直接消费现有 `runtime_nav`，不复制导航构建和身份判断。
- 通过原生 HTML 交互保留无脚本和键盘可用性。

**Non-Goals:**

- 不建立新的全站响应式导航体系。
- 不实现通知、头像上传、底部导航、当前页面高亮或菜单选择记忆。
- 不修改登录前的 Workspace 门禁页和报名工作台。

## Decisions

### 1. 新增 Workspace 首页专用 partial

新增 `templates/workspace/partials/compact_header.html`，仅由完整成员首页 `templates/workspace/index.html` 引用。共享 `templates/partials/runtime_header.html` 保持原样，其他页面的视觉和回归范围不变。

未给共享 partial 增加模式参数，因为大量调用点都依赖其当前默认行为，条件化会让一个简单首页步骤变成全站导航重构。未把结构直接全部写入 `index.html`，因为独立 partial 更容易测试页头边界，也避免首页模板继续膨胀。

### 2. 使用原生 `details` 和 `summary` 实现菜单

页头右侧使用 `details`，`summary` 作为带“页面导航”可访问名称的菜单触发器，展开内容包含语义化 `nav`。该结构不需要 JavaScript，支持浏览器原生指针与键盘展开/收起。

未使用只在 hover 时出现的菜单，因为触屏和键盘不可可靠操作；未使用自定义 JavaScript 弹出层，因为本轮不需要焦点陷阱、嵌套菜单或状态同步，原生结构更小且失败模式安全。

### 3. 完整循环 `runtime_nav.items`

品牌读取 `runtime_nav.brand_label` 与 `runtime_nav.home_url`。菜单逐项循环 `runtime_nav.items`，GET 项渲染链接，POST 项渲染带 `{% csrf_token %}` 的表单和提交按钮。不得在模板中重写七个固定项目或重新判断身份。

未把当前页“工作台”从菜单中删除。虽然它指向当前页面，但需求是先完整保留全部现有入口；是否减少重复入口必须以后单独确认。

### 4. 不照搬参考稿中的铃铛和头像

当前系统没有被确认的页头通知聚合能力，头像也不是本轮导航需求。页头只显示品牌和菜单触发器；触发器可以复用本地 Lucide `menu` 图标，但必须同时提供可访问名称，并在图标增强失败时保留可见或可理解的菜单标识。

### 5. 菜单在应用画布内右对齐

页头保持白底、底部分隔线和紧凑水平内边距。菜单面板绝对定位于右侧，设置明确层级、最大可用宽度、白底、描边和轻阴影；链接允许正常换行但不制造页面横向滚动。页头不设 sticky，避免未经讨论改变滚动行为。

## Risks / Trade-offs

- [原生 details 不会自动在点击页面其他区域时关闭] → 本轮接受浏览器原生行为；再次点击 summary 可关闭，不为便利增加全局事件监听。
- [菜单包含指向当前页的“工作台”] → 按完整保留原则继续显示，后续经过用户确认后再精简。
- [品牌文字未来变长] → 左侧使用可收缩容器和安全文本换行/截断策略，菜单触发器保持 `shrink-0`。
- [菜单覆盖后续内容] → 使用定位和层级覆盖而不推挤布局，人工检查窄屏边界和焦点顺序。
- [Lucide 未增强时图标不可见] → 菜单触发器保留文字或安全 fallback，不以图标作为唯一可理解内容。

## Migration Plan

1. 新增专用 compact header partial，并只替换完整 Workspace 首页 include。
2. 增加页头作用范围、导航完整性、顺序、URL、方法和 CSRF 回归测试。
3. 更新成员 Workspace 文档并重建 Tailwind CSS。
4. 在窄屏和宽屏检查菜单展开边界、键盘操作和后续内容位置。
5. 若需回滚，将首页 include 恢复为共享 runtime header；无数据或权限迁移。
