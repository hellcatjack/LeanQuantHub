# 实盘交易账户概览标签中文化 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为实盘交易页面的账户概览与全量账户标签提供中文标签映射，未知标签回退英文。

**Architecture:** 在 i18n 中新增 IB 标签映射，前端通过 `getMessage` 读取映射并在渲染层统一转换标签；不改后端。

**Tech Stack:** React, TypeScript, Vite, Vitest, 自研 i18n（`frontend/src/i18n.tsx`）。

---

### Task 1: 新增标签解析单元测试（TDD）

**Files:**
- Create: `frontend/src/utils/accountSummary.test.ts`
- (Future) Create: `frontend/src/utils/accountSummary.ts`

**Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";
import { resolveAccountSummaryLabel } from "./accountSummary";

describe("resolveAccountSummaryLabel", () => {
  it("returns mapped label when exists", () => {
    const map = { NetLiquidation: "净清算值" };
    expect(resolveAccountSummaryLabel("NetLiquidation", map)).toBe("净清算值");
  });

  it("falls back to key when missing", () => {
    expect(resolveAccountSummaryLabel("UnknownTag", {})).toBe("UnknownTag");
  });

  it("falls back when map is not an object", () => {
    expect(resolveAccountSummaryLabel("NetLiquidation", "bad" as any)).toBe("NetLiquidation");
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- src/utils/accountSummary.test.ts`
Expected: FAIL with module not found or missing export.

---

### Task 2: 实现标签解析工具

**Files:**
- Create: `frontend/src/utils/accountSummary.ts`

**Step 3: Write minimal implementation**

```ts
export const resolveAccountSummaryLabel = (key: string, rawMap?: unknown): string => {
  if (!rawMap || typeof rawMap !== "object") {
    return key;
  }
  const value = (rawMap as Record<string, unknown>)[key];
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  return key;
};
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- src/utils/accountSummary.test.ts`
Expected: PASS (3 tests).

**Step 5: Commit**

```bash
git add frontend/src/utils/accountSummary.ts frontend/src/utils/accountSummary.test.ts
git commit -m "test: add account summary label resolver"
```

---

### Task 3: 扩展 i18n 以读取标签映射

**Files:**
- Modify: `frontend/src/i18n.tsx`

**Step 6: Write failing test (optional, only if adding i18n unit test)**

If adding i18n test, create `frontend/src/i18n.test.tsx` to assert `getMessage("trade.accountSummaryTags")` returns object in zh locale.

**Step 7: Implement i18n changes**

Add to `I18nContextValue`:
```ts
getMessage: (key: string) => MessageTree | string | undefined;
```

Provide default value and provider implementation:
```ts
const getMessage = (key: string) => {
  const parts = key.split(".");
  let current: MessageTree | string | undefined = messages[locale];
  for (const part of parts) {
    if (!current || typeof current === "string") {
      return undefined;
    }
    current = current[part];
  }
  return current;
};
```

Add new i18n entries (zh + en) under `trade`:
```ts
accountSummaryTags: {
  NetLiquidation: "净清算值",
  TotalCashValue: "现金总额",
  AvailableFunds: "可用资金",
  BuyingPower: "购买力",
  GrossPositionValue: "持仓总值",
  EquityWithLoanValue: "含借贷权益",
  UnrealizedPnL: "未实现盈亏",
  RealizedPnL: "已实现盈亏",
  InitMarginReq: "初始保证金",
  MaintMarginReq: "维持保证金",
  AccruedCash: "应计现金",
  CashBalance: "现金余额",
  // 可按需要补充更多常见标签
}
```

For en, keep same key/value or provide friendly English labels.

**Step 8: Run unit tests**

Run: `cd frontend && npm test`
Expected: PASS.

**Step 9: Commit**

```bash
git add frontend/src/i18n.tsx
# plus optional i18n test file if created
git commit -m "feat: add account summary tag i18n mapping"
```

---

### Task 4: LiveTradePage 使用映射渲染标签

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`

**Step 10: Write failing test (optional)**

If adding integration test, extend `frontend/src/pages/LiveTradePage.test.ts` to render with a custom i18n provider and assert translated labels appear.

**Step 11: Implement UI changes**

- 从 `useI18n` 获取 `getMessage`。
- 使用 `resolveAccountSummaryLabel` 将 `item.key` 与表格 `key` 转为中文。

**Step 12: Run tests**

Run: `cd frontend && npm test`
Expected: PASS.

**Step 13: Build frontend & restart service**

```bash
cd frontend && npm run build
systemctl --user restart stocklean-frontend
```

**Step 14: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx
git commit -m "feat: localize live trade account summary tags"
```

---

### Task 5: 验证

- 手动打开“实盘交易”页面，点击刷新。
- 账户概览卡片与全量账户标签表格显示中文标签。
- 未翻译标签保持英文显示。

