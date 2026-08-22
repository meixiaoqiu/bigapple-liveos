## Context

参见 `proposal.md` 的动机说明。当前 Workspace 模板直接写出四组入口及 Django 权限条件，入口使用小型 `btn` 样式；页面已经固定在 480px 竖版容器中。仓库已经构建并提交本地 `theme/static/js/dist/lucide.min.js`，无需新增网络资源。

## Goals / Non-Goals

**Goals:**

- 仅调整现有入口的 HTML 结构和视觉层级，使其接近参考稿的三列图标卡片。
- 保持模板中的 URL、显示条件、分组和组内顺序逐项不变。
- 在 JavaScript 不可用时保留完整可操作文字链接。

**Non-Goals:**

- 不把入口列表抽象成新的服务器端导航配置。
- 不实现设计稿底部导航，也不改变欢迎区、“我的事务”或其他模块。
- 不引入外部图标 CDN、新前端框架或新后端查询。

## Decisions

### 复用本地 Lucide 资源

模板在页面末尾加载 `{% static 'js/dist/lucide.min.js' %}`，然后调用 `lucide.createIcons()` 增强带 `data-lucide` 的占位元素。图标元素设置 `aria-hidden="true"`，链接文字承担完整名称与可访问名称。

未采用外部 CDN，因为这会增加外部可用性和内容安全依赖；未手写 SVG，因为入口数量多，重复的 SVG 标记会显著增加模板噪音。仓库已有 Lucide 构建产物，所以这不是新增依赖。

### 保留模板权限分支，原位替换视觉结构

继续使用现有 Django `{% if %}` 和 `{% url %}`，只把分组容器和 `btn` 链接替换为语义化分组与卡片链接。

未在本轮引入服务器端入口配置列表，因为这会扩大到上下文结构、权限表达和测试接口；渐进式改版更适合先锁定可见结果，再决定是否重构重复模板。

### 固定三列网格并保留分组标题

每个分组使用 `grid-cols-3`。在 480px 页面容器内，三列最接近参考稿的卡片密度；在更窄屏幕上仍保持同一竖版设计，不引入桌面/移动断点差异。保留“个人功能”“治理职责”“考试维护”“运营管理”标题，以防较多职责入口混成无语义的长列表。

### 图标映射按业务语义固定

| 入口 | Lucide 图标 |
| --- | --- |
| 任务中心 | `clipboard-list` |
| 财务 / 报销 | `receipt-text` |
| 申请执衡者 | `gavel` |
| 积分转账 | `arrow-left-right` |
| 兑换订单 | `gift` |
| 公开资料 | `contact` |
| 成员报名审核 | `user-check` |
| 招募方向 | `megaphone` |
| 财务职责 | `badge-dollar-sign` |
| 待处理提案 | `file-check-2` |
| 执衡者考试配置 | `settings` |
| 创建任务 | `list-plus` |
| 任务验收 | `clipboard-check` |
| 兑换履约 | `package-check` |
| 积分预算 | `wallet-cards` |
| 商户结算 | `landmark` |
| 资源库存 | `warehouse` |
| 采购管理 | `shopping-cart` |

## Risks / Trade-offs

- [三列在极窄屏幕上使长名称换行] → 卡片采用稳定的最小高度、居中布局和允许文字自然换行，不截断名称。
- [图标脚本加载失败] → 保留原生链接文字，图标只是渐进增强，不阻断导航。
- [权限分支在视觉重构中被误改] → 逐项保留原条件并用普通成员、治理职责和运营职责测试覆盖。
- [模板 Tailwind 类未进入编译产物] → 修改后运行项目既有 Tailwind build 并提交生成的 CSS。

## Migration Plan

1. 原位替换模板导航结构并加载本地图标脚本。
2. 更新页面测试和产品文档，构建 Tailwind CSS。
3. 运行定向测试、项目检查和 OpenSpec strict validation。
4. 若需回滚，只需恢复模板、测试、文档和同轮 CSS 产物；没有数据迁移或兼容状态。
