# Live Trade Page Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将实盘交易页面按“连接→项目绑定→账户→持仓→下单→监控”主流程重排，主次分层，并统一刷新节奏与监控定义。

**Architecture:** 以 `LiveTradePage` 为主入口，抽离布局/刷新常量与分区定义到独立工具模块；主页面仅保留高频模块，其他模块折叠到“高级/详情”区域；监控区以 Orders 为默认 Tab 且 15s 轮询。

**Tech Stack:** React + Vite + TypeScript, Vitest, Playwright

---

### Task 1: 新增页面分区与刷新常量（TDD）

**Files:**
- Create: `frontend/src/utils/liveTradeLayout.ts`
- Create: `frontend/src/utils/liveTradeLayout.test.ts`

**Step 1: Write the failing test**

```ts
import { describe, it, expect } from "vitest";
import { getLiveTradeSections, LIVE_TRADE_REFRESH_MS } from "./liveTradeLayout";

describe("live trade layout", () => {
  it("defines main and advanced sections in order", () => {
    const sections = getLiveTradeSections();
    expect(sections.main).toEqual([
      "connection",
      "project",
      "account",
      "positions",
      "monitor",
    ]);
    expect(sections.advanced).toContain("config");
    expect(sections.advanced).toContain("marketHealth");
  });

  it("uses agreed refresh intervals", () => {
    expect(LIVE_TRADE_REFRESH_MS.connection).toBe(10000);
    expect(LIVE_TRADE_REFRESH_MS.monitor).toBe(15000);
    expect(LIVE_TRADE_REFRESH_MS.account).toBe(60000);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --runInBand src/utils/liveTradeLayout.test.ts`
Expected: FAIL with module not found.

**Step 3: Write minimal implementation**

```ts
export const LIVE_TRADE_REFRESH_MS = {
  connection: 10000,
  monitor: 15000,
  account: 60000,
};

export type LiveTradeSectionKey =
  | "connection"
  | "project"
  | "account"
  | "positions"
  | "monitor"
  | "config"
  | "marketHealth"
  | "contracts"
  | "history"
  | "guard"
  | "execution"
  | "symbolSummary";

export const getLiveTradeSections = () => ({
  main: ["connection", "project", "account", "positions", "monitor"] as LiveTradeSectionKey[],
  advanced: [
    "config",
    "marketHealth",
    "contracts",
    "history",
    "guard",
    "execution",
    "symbolSummary",
  ] as LiveTradeSectionKey[],
});
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --runInBand src/utils/liveTradeLayout.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/utils/liveTradeLayout.ts frontend/src/utils/liveTradeLayout.test.ts
git commit -m "test: define live trade layout constants"
```

---

### Task 2: 调整文案与 i18n（主/高级分区提示）

**Files:**
- Modify: `frontend/src/i18n.tsx`

**Step 1: Add new keys**

新增（示例）：
- `trade.mainSectionTitle` / `trade.advancedSectionTitle`
- `trade.marketHealthTitle` / `trade.marketHealthMeta`
- `trade.marketHealthStatus` / `trade.marketHealthUpdatedAt`
- `trade.sectionUpdatedAt`

**Step 2: Run unit tests**

Run: `cd frontend && npm run test -- --runInBand`
Expected: PASS

**Step 3: Commit**

```bash
git add frontend/src/i18n.tsx
git commit -m "feat: add live trade section labels"
```

---

### Task 3: LiveTradePage 主次重排与刷新节奏调整（TDD + 实现）

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- (Optional) Modify: `frontend/src/styles.css`
- Modify: `frontend/tests/live-trade.spec.ts`

**Step 1: Update Playwright expectations (fail first)**

- 更新 `live-trade.spec.ts`：
  - 连接状态仍可见
  - 行情健康使用新的标题/标识
  - 不再依赖“行情订阅卡片”作为独立卡片

Run: `cd frontend && npm run test:e2e -- --project=chromium --grep "live trade page"`
Expected: FAIL (UI 尚未调整)

**Step 2: Implement UI re-layout**

关键改动：
- 移除 `overview` 与 `snapshot` 卡片，或合并其关键信息到“连接状态/行情健康”。
- 将 `project binding` 区块内展示决策快照信息（保留现有字段）。
- 新增“行情源健康”卡片：整合 `ibStreamStatus` + `ibMarketHealth` 状态展示，主页面仅给出状态与最后更新时间；详细操作与配置归入高级区。
- 使用 `getLiveTradeSections()` 控制主/高级区块顺序；高级区使用 `<details>` 收纳。
- 监控区域默认 Tab=Orders 保持；增加 15s 轮询 `loadTradeActivity`（当 Tab 为 receipts 时轮询 `loadTradeReceipts`）。
- 刷新节奏：连接/行情 10s，监控 15s，账户/持仓 60s。替换原 5s 与 10s 逻辑。
- 所有区块展示 `last updated` 信息（已存在字段则直接显示）。

**Step 3: Run unit + e2e tests**

Run:
- `cd frontend && npm run test -- --runInBand`
- `cd frontend && npm run test:e2e -- --project=chromium --grep "live trade"`

Expected: PASS (或标注需更新的断言)

**Step 4: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/styles.css frontend/tests/live-trade.spec.ts
git commit -m "feat: reorganize live trade main/advanced sections"
```

---

### Task 4: 统一监控区回执定义与刷新提示

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/tests/live-trade-receipts.spec.ts`

**Step 1: Update tests**

- 调整回执区测试以适配默认 Orders tab + Receipt tab 轮询行为。

Run: `cd frontend && npm run test:e2e -- --project=chromium --grep "receipts"`
Expected: FAIL (旧 UI 假设)

**Step 2: Implement tweaks**

- Receipts tab 切换时立即刷新，并显示最后刷新时间。
- 监控区标题/说明明确“订单提交/成交回执在此展示”。

**Step 3: Re-run tests**

Run: `cd frontend && npm run test:e2e -- --project=chromium --grep "receipts"`
Expected: PASS

**Step 4: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/tests/live-trade-receipts.spec.ts
git commit -m "test: align live trade receipts monitoring"
```

---

### Task 5: 前端构建与服务重启

**Files:**
- None (build output)

**Step 1: Build**

Run: `cd frontend && npm run build`
Expected: build success

**Step 2: Restart service**

Run: `systemctl --user restart stocklean-frontend`
Expected: service restarted

---

### Task 6: 总体验证

**Step 1: 手动验收**

- 进入 `http://<host>:8081/live-trade`
- 确认主区块顺序：连接 → 项目绑定 → 账户 → 持仓 → 监控
- 确认“行情源健康”存在并展示状态
- 切换监控 Tab，确认 15s 刷新
- TWS 重启后，连接/持仓提示过期并可刷新恢复

**Step 2: Commit (if any extra)**

```bash
git status -sb
```

---

## Notes
- 基线测试当前在仓库顶层 `pytest -q` 会因 `ModuleNotFoundError: app` 失败，执行计划时需仅跑前端测试。
- 前端文案必须同步更新到 `frontend/src/i18n.tsx`。
