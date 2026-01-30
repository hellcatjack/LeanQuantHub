# Live Trade Bridge & i18n Controls Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复实盘交易页面的 i18n 异常文案，并新增 Lean Bridge 连接状态/刷新治理（自动 + 手动 + 监控），同时在下单时提供桥接状态软提示。

**Architecture:** 后端新增 Lean Bridge 状态与刷新接口，使用 JobLock + 轻量刷新状态文件记录刷新结果；前端定时拉取状态、提供手动刷新与自动刷新开关，并在下单回执区展示桥接提示；i18n 缺失 key 全部补齐。

**Tech Stack:** FastAPI + SQLAlchemy + MySQL, React + Vite, Playwright, pytest

---

### Task 1: i18n 缺失 key 的前置测试

**Files:**
- Create: `frontend/src/i18n.liveTradeBridge.test.tsx`

**Step 1: Write the failing test**
```tsx
import { describe, expect, it } from "vitest";
import { buildTestI18n } from "../testUtils/i18n";

const keys = [
  "trade.mainSectionTitle",
  "trade.marketHealthTitle",
  "trade.marketHealthUpdatedAt",
  "trade.sectionUpdatedAt",
  "trade.receiptsTitle",
  "trade.advancedSectionTitle",
];

describe("live trade i18n", () => {
  it("has zh translations for live trade bridge keys", () => {
    const { t } = buildTestI18n("zh");
    keys.forEach((key) => expect(t(key)).not.toBe(key));
  });

  it("has en translations for live trade bridge keys", () => {
    const { t } = buildTestI18n("en");
    keys.forEach((key) => expect(t(key)).not.toBe(key));
  });
});
```

**Step 2: Run test to verify it fails**
Run: `cd frontend && npm run test -- src/i18n.liveTradeBridge.test.tsx`
Expected: FAIL (missing translations)

**Step 3: Commit**
```bash
git add frontend/src/i18n.liveTradeBridge.test.tsx
git commit -m "test: add live trade i18n coverage"
```

---

### Task 2: 补齐实盘交易 i18n 文案

**Files:**
- Modify: `frontend/src/i18n.tsx`

**Step 1: Implement translations**
- 在中英文 `trade` 下补齐：
  - `mainSectionTitle`
  - `marketHealthTitle`
  - `marketHealthUpdatedAt`
  - `sectionUpdatedAt`
  - `receiptsTitle`
  - `advancedSectionTitle`

**Step 2: Run test to verify it passes**
Run: `cd frontend && npm run test -- src/i18n.liveTradeBridge.test.tsx`
Expected: PASS

**Step 3: Commit**
```bash
git add frontend/src/i18n.tsx
git commit -m "fix: fill live trade i18n labels"
```

---

### Task 3: Lean Bridge 刷新状态模型 + 服务层

**Files:**
- Modify: `backend/app/services/lean_bridge_watchdog.py`
- Create: `backend/tests/test_lean_bridge_watchdog.py`

**Step 1: Write the failing test**
```python
from datetime import datetime, timezone
from pathlib import Path

from app.services import lean_bridge_watchdog as w


def test_refresh_state_roundtrip(tmp_path: Path):
    root = tmp_path / "lean_bridge"
    root.mkdir()
    w.write_refresh_state(root, result="success", reason="manual", message="ok")
    state = w.read_refresh_state(root)
    assert state["last_refresh_result"] == "success"
    assert state["last_refresh_reason"] == "manual"
    assert state["last_refresh_message"] == "ok"
    assert "last_refresh_at" in state
```

**Step 2: Run test to verify it fails**
Run: `pytest backend/tests/test_lean_bridge_watchdog.py::test_refresh_state_roundtrip -v`
Expected: FAIL (functions missing)

**Step 3: Implement minimal service changes**
- 在 `lean_bridge_watchdog.py` 新增：
  - `read_refresh_state(root: Path) -> dict`
  - `write_refresh_state(root: Path, result: str, reason: str, message: str | None)`
  - `build_bridge_status(root)`（合并 `read_bridge_status` + refresh state）
  - `refresh_bridge(...)`（锁/节流/执行脚本/写入 refresh state）

**Step 4: Run test to verify it passes**
Run: `pytest backend/tests/test_lean_bridge_watchdog.py::test_refresh_state_roundtrip -v`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/lean_bridge_watchdog.py backend/tests/test_lean_bridge_watchdog.py
git commit -m "feat: add lean bridge refresh state"
```

---

### Task 4: 后端桥接状态与刷新接口

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/brokerage.py`
- Test: `backend/tests/test_lean_bridge_watchdog.py` (extend)

**Step 1: Extend schema**
- Add: `IBBridgeStatusOut`, `IBBridgeRefreshOut`

**Step 2: Extend tests**
```python
def test_build_bridge_status_contains_refresh_state(tmp_path: Path):
    root = tmp_path / "lean_bridge"
    root.mkdir()
    w.write_refresh_state(root, result="skipped", reason="rate_limited", message=None)
    status = w.build_bridge_status(root)
    assert status["last_refresh_result"] == "skipped"
    assert status["last_refresh_reason"] == "rate_limited"
```

**Step 3: Implement routes**
- `GET /api/brokerage/bridge/status`
- `POST /api/brokerage/bridge/refresh`

**Step 4: Run tests**
Run: `pytest backend/tests/test_lean_bridge_watchdog.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/schemas.py backend/app/routes/brokerage.py backend/tests/test_lean_bridge_watchdog.py
git commit -m "feat: add lean bridge status endpoints"
```

---

### Task 5: 下单软提示（B 策略）

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/trade_direct_order.py`
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`

**Step 1: Add response fields**
- `TradeDirectOrderOut` 增加可选字段：`bridge_status`、`refresh_result`

**Step 2: Update order submit**
- 在 `submit_direct_order` 调用 `build_bridge_status`，必要时 `refresh_bridge`（reason=order_submit, force=false）
- 将结果写入响应（软提示，不阻断）

**Step 3: Update UI**
- 在回执/提示区域展示桥接警告（黄色提示）

**Step 4: Commit**
```bash
git add backend/app/schemas.py backend/app/services/trade_direct_order.py frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx
git commit -m "feat: add bridge warning to direct orders"
```

---

### Task 6: 实盘交易页桥接状态 UI 与自动刷新

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Modify: `frontend/src/utils/liveTradeLayout.ts`
- Test: `frontend/tests/live-trade.spec.ts`

**Step 1: Update UI**
- 新增“桥接状态卡片”字段：最后心跳、是否过期、最后刷新（时间/来源/结果）
- 添加“刷新 Lean Bridge”按钮 + 自动刷新开关

**Step 2: Update Playwright tests**
- 增加检查新字段的断言（中文/英文均可）

**Step 3: Run tests**
Run: `cd frontend && npm run test:e2e -- --grep "live trade"`
Expected: PASS

**Step 4: Commit**
```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx frontend/tests/live-trade.spec.ts frontend/src/utils/liveTradeLayout.ts
git commit -m "feat: add lean bridge status UI"
```

---

### Task 7: Build & Restart Frontend

**Step 1: Build**
Run: `cd frontend && npm run build`

**Step 2: Restart**
Run: `systemctl --user restart stocklean-frontend`

---

### Task 8: Verification (Playwright scan)

**Step 1: Run scan**
Run: `node frontend/scripts/scan-live-trade-i18n.mjs`
Expected: 0 suspicious i18n keys

**Step 2: Record outcome**
- 在交付说明中贴出扫描结果摘要

---

### Task 9: Final Merge Preparation

**Step 1: Run backend tests**
Run: `pytest backend/tests/test_lean_bridge_watchdog.py`

**Step 2: Ensure git clean**
Run: `git status -sb`

**Step 3: Commit any leftover**

---

