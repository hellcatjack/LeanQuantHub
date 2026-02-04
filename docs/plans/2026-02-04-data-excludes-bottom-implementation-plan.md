# 数据页全局排除列表下移 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将数据页“全局排除列表”移动到页面最底部，并增加自动化测试防回归。

**Architecture:** 仅调整 `DataPage` 渲染顺序；用 Playwright 断言排除列表在所有卡片标题中位于最后。

**Tech Stack:** React + Vite、Playwright。

> 说明：项目规则禁止使用 git worktree，本计划直接在主工作区执行。

### Task 1: 先写失败测试（Playwright）

**Files:**
- Modify: `frontend/tests/data-excludes.spec.ts`

**Step 1: Write the failing test**

在现有用例末尾新增断言（示意）：

```ts
const titles = await page.locator(".card-title").allTextContents();
const last = titles[titles.length - 1] || "";
expect(last).toMatch(/全局排除列表|Global Exclude List/);
```

**Step 2: Run test to verify it fails**

Run:
`cd frontend && E2E_BASE_URL=http://127.0.0.1:4173 npm run test:e2e -- tests/data-excludes.spec.ts`

Expected: FAIL（当前排除列表不在最后）。

**Step 3: Commit**

```bash
git add frontend/tests/data-excludes.spec.ts
git commit -m "Add data excludes position assertion"
```

### Task 2: 调整 DataPage 顺序

**Files:**
- Modify: `frontend/src/pages/DataPage.tsx`

**Step 1: Implement minimal change**

将“全局排除列表”卡片从 `data-columns` 中部移到页面最末尾（在 PIT / PITFund / Sync 之后）。逻辑与状态不变，仅移动 JSX 区块位置。

**Step 2: Run test to verify it passes**

Run:
`cd frontend && E2E_BASE_URL=http://127.0.0.1:4173 npm run test:e2e -- tests/data-excludes.spec.ts`

Expected: PASS

**Step 3: Run build & restart**

```bash
cd frontend && npm run build
systemctl --user restart stocklean-frontend
```

**Step 4: Commit**

```bash
git add frontend/src/pages/DataPage.tsx
git commit -m "Move data excludes card to page bottom"
```

### Task 3: 手动验证

**Files:** None

**Step 1: Manual check**
- 打开数据页，滚动到底部：确认“全局排除列表”位于页面最底部。
- 操作新增/编辑/禁用/启用，确保功能无回归。

