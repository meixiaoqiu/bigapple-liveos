## 1. 导航结构

- [x] 1.1 将 Workspace 顶部全部现有入口移动到“个人功能”“治理职责”“运营管理”三个具名分组，保留每个入口的文字、URL 和原有权限条件
- [x] 1.2 统一组内按钮视觉层级并实现响应式分组布局，确保无可见入口的职责分组不渲染

## 2. 回归覆盖与文档

- [x] 2.1 增加 Workspace 页面测试，验证分组标题、入口归属、权限可见性、链接目标和统一按钮样式
- [x] 2.2 更新成员 Workspace 产品文档，说明顶部导航的三组结构及权限边界不变

## 3. 构建与验证

- [x] 3.1 运行 Tailwind 构建并更新编译后的主题 CSS
- [x] 3.2 运行相关 Workspace 测试、Django check、OpenSpec strict validation 和两个仓库的 `git diff --check`

## 4. 公共页头换行回归修复

- [x] 4.1 禁止公共运行时页头的链接与提交按钮在标签内部换行，并增加模板回归测试
- [x] 4.2 重新构建 Tailwind CSS，运行相关测试、OpenSpec strict validation 和 `git diff --check`
