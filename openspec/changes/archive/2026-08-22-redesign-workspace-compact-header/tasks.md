## 1. Workspace 专用紧凑页头

- [x] 1.1 新增 `templates/workspace/partials/compact_header.html`，使用现有品牌文字和首页 URL，在同一行提供品牌入口和可访问的原生折叠菜单触发器
- [x] 1.2 在菜单中按 `runtime_nav.items` 原顺序循环全部项目，GET 项保留链接，POST 项保留带 CSRF 的表单，不硬编码身份或入口列表
- [x] 1.3 仅将完整成员首页 `templates/workspace/index.html` 切换到专用 partial，确认共享 `templates/partials/runtime_header.html` 及其他调用页面没有修改
- [x] 1.4 为页头和右对齐菜单面板设置紧凑白底、分隔线、可视焦点、画布内宽度及层级样式，确保 Lucide 未增强时菜单标识仍可理解
- [x] 1.5 将共享 `runtime_nav.brand_label` 统一为用户确认的“大苹果社区”，不改变导航项目构建、权限、顺序、URL 或请求方法

## 2. 回归覆盖

- [x] 2.1 增加 Workspace 首页测试，验证专用页头、品牌文字、品牌 URL、原生折叠结构和默认收起状态
- [x] 2.2 验证已登录 `runtime_nav.items` 的全部文字、URL、顺序和 GET/POST 方法保持不变，特别验证退出仍为带 CSRF 的 POST 表单
- [x] 2.3 验证首页没有新增通知、未读数量、头像菜单或底部导航，并保留欢迎区、状态摘要、快捷操作、我的事务和后续模块
- [x] 2.4 增加作用范围测试，验证任务中心等 Workspace 子页面、报名工作台和其他运行时页面继续使用共享页头而不出现专用页头

## 3. 文档、构建与验证

- [x] 3.1 更新 `bigapple-docs/docs/product/member-workspace.md`，记录首页专用紧凑页头、菜单完整性、POST 安全和其他页面不变的边界
- [x] 3.2 运行 Tailwind build 并提交更新后的 `theme/static/css/dist/styles.css`，确认没有意外改写 Lucide 生成资源版本
- [x] 3.3 在窄屏和宽屏人工检查默认收起、展开边界、键盘展开/收起、焦点顺序、长品牌和菜单项目换行，不产生横向溢出
- [x] 3.4 运行 Workspace 定向测试、项目检查、Django check、迁移漂移检查、OpenSpec strict validation 及 LiveOS 与 docs 两个仓库的 `git diff --check`
- [x] 3.5 审查最终 diff，确认 `live_os/runtime_nav.py` 仅修改品牌文案，且未修改共享 `runtime_header.html`、view、模型、领域服务、URL、权限判断、导航行为或技术契约
