## Purpose

为 Workspace 首页建立跨手机、平板和桌面统一使用的竖版页面画布，使后续视觉改造可以逐模块实施，同时保持现有功能和权限边界不变。

## ADDED Requirements

### Requirement: Workspace 首页采用 480px 最大宽度
系统 SHALL 以完整可用宽度渲染 Workspace 首页，并 MUST 将宽屏设备上的页面最大宽度限制为 `480px` 且水平居中。页头与主体 SHALL 位于同一个至少占满视口高度的连续白色应用画布中，画布之外 SHALL 保留灰色页面背景。

#### Scenario: 窄于 480px 的设备访问
- **WHEN** 成员在视口宽度小于或等于 `480px` 的设备打开 Workspace 首页
- **THEN** 页面使用可用视口宽度且不产生由固定宽度导致的横向滚动
- **THEN** 白色应用画布铺满可用页面宽度

#### Scenario: 宽于 480px 的设备访问
- **WHEN** 成员在视口宽度大于 `480px` 的设备打开 Workspace 首页
- **THEN** 页头与主体的内容宽度均不超过 `480px`
- **THEN** 页头与主体沿同一垂直轴水平居中
- **THEN** 页头与主体位于同一块连续白色画布中，画布两侧显示灰色外部背景

### Requirement: Workspace 首页保持单列竖版布局
系统 SHALL 在所有视口宽度下保持 Workspace 首页主要模块为同一单列顺序，不得因外部视口达到桌面断点而将 480px 容器中的主要模块强制拆成多列。

#### Scenario: 桌面设备访问竖版 Workspace
- **WHEN** 外部视口达到桌面断点但 Workspace 页面已受 480px 最大宽度约束
- **THEN** 导航分组、事务分组、待处理事项和核心状态继续按单列竖版顺序显示

### Requirement: 宽度改造不改变现有功能
系统 SHALL 保留宽度改造前 Workspace 首页的全部现有模块、入口、文案顺序和权限条件。

#### Scenario: 成员访问改造后的 Workspace
- **WHEN** 任意具备 Workspace 访问资格的成员打开首页
- **THEN** 其原先有权看到的模块和入口仍然存在
- **THEN** 其原先无权看到的模块和入口不会因布局改造而出现
