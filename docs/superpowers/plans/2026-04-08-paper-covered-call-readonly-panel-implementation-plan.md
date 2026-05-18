# Paper Covered Call 只读前端面板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `LiveTrade` 页面增加 `paper covered call` 的只读前端面板，展示最近 review 和聚合 audit/timeline。

**Architecture:** 新增一个纯展示组件 `CoveredCallAuditPanel`，由 `LiveTradePage` 负责取数与状态。先用 TDD 补组件/页面/Playwright 回归，再实现最小前端接线。

**Tech Stack:** React 18、Vite、Vitest、Playwright、现有 `api` Axios 封装。

---

### Task 1: 定义前端类型与失败测试

**Files:**
- Create: `frontend/src/components/trade/CoveredCallAuditPanel.tsx`
- Create: `frontend/src/components/trade/CoveredCallAuditPanel.test.tsx`
- Modify: `frontend/src/pages/LiveTradePage.test.ts`

- [ ] Step 1: 写组件失败测试，覆盖 recent 列表、audit 详情、空态
- [ ] Step 2: 运行 `cd frontend && npm run test -- src/components/trade/CoveredCallAuditPanel.test.tsx`，确认失败
- [ ] Step 3: 写最小组件与 props 类型，让测试通过
- [ ] Step 4: 运行同一命令，确认通过
- [ ] Step 5: 在 `LiveTradePage.test.ts` 新增页面接线失败测试
- [ ] Step 6: 运行 `cd frontend && npm run test -- src/pages/LiveTradePage.test.ts`，确认失败

### Task 2: 在 LiveTradePage 接入 recent/audit 数据流

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/pages/LiveTradePage.test.ts`

- [ ] Step 1: 增加 `audit/recent` 和 `audit` 的前端类型、state、fetch 方法
- [ ] Step 2: 在执行区接入 `CoveredCallAuditPanel`
- [ ] Step 3: 增加最小样式和文案
- [ ] Step 4: 运行 `cd frontend && npm run test -- src/components/trade/CoveredCallAuditPanel.test.tsx src/pages/LiveTradePage.test.ts`，确认通过

### Task 3: Playwright 只读回归

**Files:**
- Create: `frontend/tests/live-trade-covered-call-panel.spec.ts`

- [ ] Step 1: 写 E2E 失败用例，拦截 `audit/recent` 和 `audit`
- [ ] Step 2: 运行 `cd frontend && E2E_BASE_URL=http://127.0.0.1:4173 npm run test:e2e -- tests/live-trade-covered-call-panel.spec.ts`，确认失败
- [ ] Step 3: 修正前端细节直到用例通过
- [ ] Step 4: 重新运行同一命令，确认通过

### Task 4: 最终验证

**Files:**
- Modify: `frontend/src/components/trade/CoveredCallAuditPanel.tsx`
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/components/trade/CoveredCallAuditPanel.test.tsx`
- Test: `frontend/src/pages/LiveTradePage.test.ts`
- Test: `frontend/tests/live-trade-covered-call-panel.spec.ts`

- [ ] Step 1: 运行 `cd frontend && npm run test -- src/components/trade/CoveredCallAuditPanel.test.tsx src/pages/LiveTradePage.test.ts`
- [ ] Step 2: 运行 `cd frontend && E2E_BASE_URL=http://127.0.0.1:4173 npm run test:e2e -- tests/live-trade-covered-call-panel.spec.ts`
- [ ] Step 3: 运行 `cd frontend && npm run build`
- [ ] Step 4: 运行 `systemctl --user restart stocklean-frontend && systemctl --user status stocklean-frontend --no-pager`
