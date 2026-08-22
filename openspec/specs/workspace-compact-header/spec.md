# workspace-compact-header 规格

## Purpose

定义 Workspace 首页在固定竖版画布中的专用紧凑页头，使社区品牌和完整运行时导航在窄宽度下保持清晰、可访问和方法安全，同时不影响其他运行时页面。

## Requirements

### Requirement: Workspace 首页使用专用紧凑页头
系统 SHALL 仅在已登录成员的 Workspace 首页使用紧凑页头，并 SHALL 在同一行显示现有社区品牌入口和一个菜单入口。系统 MUST NOT 将该专用页头自动应用到其他 Workspace 子页面或其他运行时页面。

#### Scenario: 成员打开 Workspace 首页
- **WHEN** 已登录成员打开 `/workspace/`
- **THEN** 页面在 480px 应用画布顶部显示紧凑页头
- **THEN** 页头不再将全部运行时导航入口横向铺开

#### Scenario: 成员打开 Workspace 子页面
- **WHEN** 成员打开任务中心、财务或其他 Workspace 子页面
- **THEN** 页面继续使用变更前的公共运行时页头

### Requirement: 运行时品牌统一且品牌入口复用共享上下文
系统 SHALL 将共享运行时品牌文字统一为“大苹果社区”。紧凑页头 SHALL 使用运行时导航上下文提供的品牌文字和首页目标地址，不得在模板中写死另一套品牌名称或目标。

#### Scenario: 显示社区品牌
- **WHEN** Workspace 首页获得现有运行时导航上下文
- **THEN** 页头品牌通过 `brand_label` 显示“大苹果社区”
- **THEN** 品牌链接指向 `home_url`

#### Scenario: 其他页面使用共享运行时页头
- **WHEN** 页面继续使用共享运行时页头
- **THEN** 该页面通过同一运行时上下文显示“大苹果社区”
- **THEN** 其页头结构、导航权限、项目顺序、URL 和请求方法保持不变

### Requirement: 菜单完整保留现有导航
紧凑页头 SHALL 在默认收起的菜单中按现有 `runtime_nav.items` 顺序展示当前用户可见的全部导航项，并 MUST 保留每项现有文字、URL 和请求方法。系统 MUST NOT 因空间限制删除、重排或新增入口。

#### Scenario: 已登录成员打开菜单
- **WHEN** 已登录成员展开 Workspace 首页菜单
- **THEN** 菜单按上下文顺序显示首页、事件流、财务、资源库存、我的主页、工作台和退出等当前可见入口
- **THEN** 每项继续指向现有目标地址

#### Scenario: 运行时导航项目发生合法变化
- **WHEN** `runtime_nav.items` 根据当前身份增加、减少或调整项目
- **THEN** 紧凑菜单循环展示新的上下文结果而不是依赖硬编码项目列表

### Requirement: 退出继续使用安全方法
菜单 MUST 保留每个导航项目声明的请求方法；方法为 `post` 的项目 SHALL 渲染为带 CSRF 保护的 POST 表单，不得转换为 GET 链接。

#### Scenario: 成员点击退出
- **WHEN** `runtime_nav.items` 中的退出项目声明 `method` 为 `post`
- **THEN** 菜单使用 POST 表单提交到现有退出 URL
- **THEN** 表单包含当前请求的 CSRF 保护

### Requirement: 菜单无需脚本即可操作
菜单 SHALL 使用浏览器原生可交互结构，使键盘用户可以聚焦、展开、浏览、激活并再次收起菜单；页面脚本未执行时，菜单功能 SHALL 继续可用。

#### Scenario: 无脚本环境使用菜单
- **WHEN** 浏览器未执行 Workspace 页面脚本
- **THEN** 成员仍可使用键盘或指针展开和收起菜单
- **THEN** 菜单内 GET 链接和 POST 表单仍可操作

### Requirement: 不制造未接入的页头功能
系统 MUST NOT 仅为接近参考设计稿而新增通知铃铛、未读数量、头像菜单、底部导航或其他没有现有业务入口支持的交互。

#### Scenario: 检查紧凑页头范围
- **WHEN** 紧凑页头改造完成
- **THEN** 页头只展示现有品牌与导航能力
- **THEN** 欢迎区、状态摘要、快捷操作、我的事务和后续现有模块继续存在

### Requirement: 紧凑页头不横向溢出
紧凑页头及其收起状态 SHALL 适配完整可用宽度至最大 `480px` 的应用画布，不得因品牌或菜单入口产生页面级横向滚动。展开菜单 SHALL 保持在应用画布可视边界内并覆盖于后续内容之上。

#### Scenario: 窄屏显示页头
- **WHEN** 成员在窄于 `480px` 的视口打开 Workspace 首页并展开菜单
- **THEN** 品牌、菜单入口和菜单面板保持在可视宽度内
- **THEN** 页面不产生由页头造成的横向滚动
