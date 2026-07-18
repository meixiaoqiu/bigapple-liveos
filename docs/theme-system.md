# 主题系统

本文档说明 Big Apple Live OS 的公众页面主题机制。当前目标是工程基础设施，不是最终视觉设计。

## 设计包与运行时边界

- `../big-apple-design` 是视觉规范和设计包源头，用于沉淀完整主题方向、素材组织、设计说明和可选模板草案。
- `big-apple-live-os` 是运行时实现，只放实际被 Django 渲染和静态资源系统引用的模板、组件、partial 和静态资源。
- 同名主题目录不代表两边文件必须逐字一致。设计包可以更完整，运行时可以保留更小的可运行切片。
- 从设计包同步到运行时时，只同步当前页面真正引用的文件；同步后必须运行观察台/主题测试。

同步规则：

1. 改主题视觉语言、素材体系或组件规范时，先改 `big-apple-design`。
2. 改运行时 bug、模板变量、HTMX partial 或 Django fallback 时，先改 `big-apple-live-os`。
3. 把设计包内容拷入运行时时，记录同步范围和取舍，不要无说明地覆盖运行时模板。
4. 运行时模板不能发起业务查询，只消费 `dashboard_context`。
5. 运行时缺少素材时显示空状态或安全 fallback，不注入演示数据。

## 新增主题

1. 在 `live_os/settings.py` 的 `THEME_CONFIGS` 中新增主题配置。
2. 创建模板目录：`templates/themes/<theme_key>/`。
3. 创建静态资源目录：`static/themes/<theme_key>/`。
4. 只覆盖需要变化的模板、组件、partial 和资源；缺失内容会回退到 `default_game`。
5. 修改模板 class 或新增 Tailwind class 后执行：

```bash
python manage.py tailwind build
```

## 目录结构

标准主题模板目录：

```text
templates/themes/<theme_key>/
  base.html
  dashboard.html
  components/
    top_nav.html
    bottom_nav.html
    map_stage.html
    map_pin.html
    mission_card.html
    event_card.html
    photo_card.html
    stat_chip.html
    achievement_badge.html
    reward_modal.html
    empty_state.html
    loading_skeleton.html
  partials/
    mission_list.html
    event_feed.html
    map_points.html
    risk_panel.html
    capacity_panel.html
```

标准主题静态资源目录：

```text
static/themes/<theme_key>/
  css/
    tokens.css
    theme.css
    animations.css
  js/
    theme.js
    htmx-hooks.js
  img/
    mascot/
    buildings/
    markers/
    badges/
    rewards/
    stickers/
    photos-placeholder/
  svg/
    icons/
    map/
    ui/
  lottie/
  audio/
```

## THEME_CONFIGS

每个主题至少包含：

- `key`：稳定主题键。
- `name`：显示名称。
- `description`：用途说明。
- `template_dir`：模板目录，例如 `themes/default_game`。
- `static_dir`：静态资源目录，例如 `themes/default_game`。
- `daisy_theme`：写入 `<html data-theme="...">`。
- `preview_image`：预览图路径，可为空。
- `is_active`：是否出现在可切换主题列表。
- `supports_mobile`：是否声明移动端支持。
- `supports_animations`：是否加载主题动画 CSS。

## default_game

`default_game` 是主题系统的主 fallback。新增主题应直接声明自己的 `template_dir`，缺失模板回退到 `default_game`。

## dashboard_context

`observer.dashboard_theme.build_dashboard_theme_context(request, raw_data=None)` 返回所有主题消费的展示层数据契约。业务查询仍由 `observer.page_context` 等读模型模块负责，`dashboard_context` 只做包装和默认值补齐。

核心结构：

```python
{
    "hero": {"title": "大苹果社区动态", "subtitle": "", "status_label": "", "status_level": "watch"},
    "stats": [],
    "missions": [],
    "events": [],
    "map_points": [],
    "photos": [],
    "achievements": [],
    "risk_summary": {"high": 0, "medium": 0, "low": 0, "resolved": 0},
    "role_pressure": [],
    "capacity": {"current": 0, "total": 0, "percent": 0, "safe_threshold": 85},
    "user_progress": {"level": 1, "xp": 0, "xp_next": 100, "points": 0, "badges_count": 0},
    "navigation": [],
}
```

模板应只依赖 `dashboard_context`，不要直接依赖业务模型字段。

## Components

组件位于 `components/`，用于渲染一个可复用 UI 单元。组件应该：

- 只读取 `dashboard_context` 或当前循环变量。
- 不发起业务查询。
- 不假设字段一定存在。
- 缺失时使用 `empty_state.html` 或默认文案。

可在模板中使用：

```django
{% load theme_tags %}
{% themed_component "mission_card.html" as mission_card_template %}
{% include mission_card_template %}
```

## Partials

partial 位于 `partials/`，用于 htmx 局部刷新。当前支持：

- `mission_list.html`
- `event_feed.html`
- `map_points.html`
- `task_detail.html`
- `risk_panel.html`
- `capacity_panel.html`
- `photo_story_feed.html`

partial view 使用同一份 `build_dashboard_theme_context`，不会返回完整页面。

## htmx 跟随主题

新增 URL：

```text
/dashboard/partials/missions/
/dashboard/partials/events/
/dashboard/partials/map-points/
/dashboard/partials/task-detail/
/dashboard/partials/risk/
/dashboard/partials/capacity/
/dashboard/partials/photo-stories/
```

查找规则：

1. `templates/themes/<active_theme>/partials/...`
2. `templates/themes/default_game/partials/...`
3. 安全 fallback

`default_game/dashboard.html` 中已经提供 30 秒任务/事件刷新、60 秒风险/容量刷新示例。

## theme_asset

模板中引用主题资源：

```django
{% load theme_tags %}
{% theme_asset "img/mascot/guide-happy.webp" as mascot_url %}
```

查找规则：

1. `static/themes/<active_theme>/img/mascot/guide-happy.webp`
2. `static/themes/default_game/img/mascot/guide-happy.webp`
3. 找不到返回空字符串

支持资源根目录：

- `img`
- `svg`
- `css`
- `js`
- `lottie`
- `audio`

## Fallback 规则

- 未知主题：回退到 `default_game`。
- 模板缺失：回退到 `default_game` 或安全占位。
- partial 缺失：回退到 `default_game`。
- component 缺失：回退到 `default_game`。
- 静态资源缺失：回退到 `default_game`，仍缺失则返回空字符串。

## 切换主题

```text
POST /themes/switch/
```

参数：

- `theme`：主题 key。
- `next`：可选，切换后的跳转地址。

主题写入 session，不修改数据库。

`GET /?theme=<theme_key>` 只用于人工验证当前请求的临时主题预览，不写入 session，也不修改数据库。需要持久切换主题时必须使用上面的 POST 入口。

## 后续接入真实素材

真实素材应只放在对应主题的 `static/themes/<theme_key>/` 下。主题模板通过 `theme_asset` 引用，不要写死 `/static/...`。

## 让 Codex 实现具体风格时的修改范围

实现某个具体主题时，优先只修改：

- `THEME_CONFIGS`
- `templates/themes/<theme_key>/`
- `static/themes/<theme_key>/`
- 必要的文档说明

不要修改数据库模型，不要重写 observer 业务查询，不要把最终视觉逻辑写进 contract-facing API 模块或核心领域服务。
