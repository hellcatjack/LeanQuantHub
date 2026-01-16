# 主菜单优化 TODO

## 目标
- 主流程入口更清晰：项目 → 数据 → 回测 → 主题库 → 系统审计
- 弱化独立“算法页”可见性，但保留入口以便需要时进入
- 菜单命名更贴合工作流与风险边界（回测/报告合并展示）

## 范围与约束
- 仅调整前端主菜单顺序与文案
- 不删除页面路由，只调整入口层级
- UI 变更后必须在 `frontend/` 目录执行 `npm run build` 并重启 `stocklean-frontend`

## 现状（基准）
- 侧边栏顺序：项目 / 主题 / 回测 / 数据 / 审计
- 算法页存在路由，但未在主菜单中展示
- 报告页已并入回测（`/reports` -> `/backtests?tab=reports`）

## 目标菜单结构
1) 项目（/projects）
2) 数据（/data）
3) 回测&报告（/backtests）
4) 主题库（/themes）
5) 系统审计（/audit-logs）

## 任务清单
### Phase 1：菜单结构与文案
- [ ] 调整 `frontend/src/components/Sidebar.tsx` 中的菜单顺序为：项目 → 数据 → 回测 → 主题库 → 系统审计
- [ ] 更新 `frontend/src/i18n.tsx` 的导航文案：
  - nav.backtests = "回测&报告"
  - nav.themes = "主题库"
  - nav.audit = "系统审计"
  - 其他保持不变

### Phase 2：算法入口弱化
- [ ] 在项目页顶部加入“算法库/模型版本摘要”的跳转入口（不在主菜单展示）
- [ ] 如需保留算法页入口，使用轻量按钮/链接并避免高频曝光

### Phase 3：验证与发布
- [ ] Playwright 自测：侧边栏顺序、文案、路由可达性
- [ ] 前端构建与重启：`cd frontend && npm run build` + `systemctl --user restart stocklean-frontend`
- [ ] 记录变更（更新文档或 UI 提示，说明主菜单调整）

## 验收标准
- 主菜单顺序与文案符合“目标菜单结构”
- 不出现“报告”独立入口
- 算法页不在主菜单出现，但可通过项目页入口进入
- 无多余横向滚动条、导航点击无路由错误

## 相关文件
- `frontend/src/components/Sidebar.tsx`
- `frontend/src/i18n.tsx`
- `frontend/src/pages/ProjectsPage.tsx`
