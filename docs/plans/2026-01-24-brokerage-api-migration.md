# Brokerage API Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace `/api/ib/*` with `/api/brokerage/*`, remove IB API probes, and update frontend to use Lean Bridge brokerage endpoints only.

**Architecture:** Introduce a new `brokerage` router that exposes the same schema as the old IB routes but sourced from Lean Bridge readers. Remove the `ib` router and update frontend calls to the new endpoints. IB API probing is removed so connection status is derived from bridge status + DB state only.

**Tech Stack:** FastAPI, SQLAlchemy, React/Vite, Playwright.

### Task 1: Add brokerage router and remove ib router (backend)

**Files:**
- Create: `backend/app/routes/brokerage.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/routes/ib.py` (delete file or keep only helpers if reused)
- Test: `backend/tests/test_brokerage_routes.py`

**Step 1: Write the failing test**

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import brokerage as brokerage_routes


def test_brokerage_settings_route():
    app = FastAPI()
    app.include_router(brokerage_routes.router)
    client = TestClient(app)
    res = client.get("/api/brokerage/settings")
    assert res.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_brokerage_routes.py::test_brokerage_settings_route`
Expected: FAIL (router missing)

**Step 3: Write minimal implementation**

Create `backend/app/routes/brokerage.py` by copying `backend/app/routes/ib.py` content and changing:
- `APIRouter(prefix="/api/brokerage", tags=["brokerage"])`
- Rename route functions to `get_brokerage_*` etc (optional but recommended)
- Update audit log action strings from `ib.*` to `brokerage.*` (optional but recommended)
- Keep schemas as-is to avoid DB migrations

Update `backend/app/main.py`:
- Replace `app.include_router(ib.router)` with `app.include_router(brokerage.router)`

Remove `backend/app/routes/ib.py` or leave an empty deprecated stub that is not included.

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_brokerage_routes.py::test_brokerage_settings_route`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/routes/brokerage.py backend/app/main.py backend/tests/test_brokerage_routes.py
# if deleting old file: git add backend/app/routes/ib.py

git commit -m "feat: add brokerage router and drop ib routes"
```

### Task 2: Remove IB API probe logic (backend)

**Files:**
- Modify: `backend/app/services/ib_settings.py`
- Modify: `backend/tests/test_ib_settings_client_id.py`

**Step 1: Write the failing test**

```python
def test_probe_ib_connection_uses_bridge_only(monkeypatch, session):
    from app.services import ib_settings
    monkeypatch.setattr(ib_settings, "_probe_ib_api", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("probe")))
    monkeypatch.setattr(ib_settings, "_probe_ib_account_session", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("probe")))
    state = ib_settings.probe_ib_connection(session, timeout_seconds=0.1)
    assert state.status in {"connected", "disconnected", "mock", "unknown"}
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_ib_settings_client_id.py::test_probe_ib_connection_uses_bridge_only`
Expected: FAIL (still probes)

**Step 3: Write minimal implementation**

In `backend/app/services/ib_settings.py`:
- Remove `_probe_ib_api` and `_probe_ib_account_session` functions
- Simplify `ensure_ib_client_id` to return settings without probing
- Update `probe_ib_connection` to only set status based on `api_mode` or TCP socket (optional) and never import ibapi

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_ib_settings_client_id.py::test_probe_ib_connection_uses_bridge_only`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_settings.py backend/tests/test_ib_settings_client_id.py

git commit -m "chore: remove ib api probing from settings"
```

### Task 3: Update frontend LiveTrade API paths and labels

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Test: `frontend/tests/live-trade-bridge.spec.ts`

**Step 1: Write the failing test**

```ts
import { test, expect } from "@playwright/test";

test("live trade uses brokerage endpoints", async ({ page }) => {
  await page.goto("/trade");
  await page.waitForTimeout(500);
  await expect(page.locator("text=Lean Bridge")) .toBeVisible();
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx playwright test tests/live-trade-bridge.spec.ts`
Expected: FAIL (text not found or old endpoints)

**Step 3: Write minimal implementation**

In `LiveTradePage.tsx`:
- Replace `/api/ib/*` with `/api/brokerage/*`
- Update card titles and hints from “IB” to “Brokerage / Lean Bridge”

In `i18n.tsx`:
- Update translations to remove “IB API” mentions and align to “Lean Bridge” terminology

**Step 4: Run test to verify it passes**

Run: `cd frontend && npx playwright test tests/live-trade-bridge.spec.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx frontend/tests/live-trade-bridge.spec.ts

git commit -m "feat: migrate live trade ui to brokerage endpoints"
```

### Task 4: Update docs & TODO

**Files:**
- Modify: `docs/todolists/IBAutoTradeTODO.md`
- Modify: `docs/plans/2026-01-24-brokerage-api-migration.md`

**Step 1: Update TODO items**

Mark tasks completed for:
- Replace `/api/ib/*` with `/api/brokerage/*`
- Remove IB API probing
- Frontend updated to Lean Bridge

**Step 2: Commit**

```bash
git add docs/todolists/IBAutoTradeTODO.md docs/plans/2026-01-24-brokerage-api-migration.md

git commit -m "docs: update plan and todo for brokerage migration"
```

---

## Verification

Run backend tests:
- `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_brokerage_routes.py backend/tests/test_ib_settings_client_id.py`

Run frontend tests:
- `cd frontend && npx playwright test tests/live-trade-bridge.spec.ts`

Build & restart (required for frontend changes):
- `cd frontend && npm run build`
- `systemctl --user restart stocklean-frontend`
