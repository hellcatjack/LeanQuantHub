# 全局排除标的清单 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在数据页面提供全局排除标的清单的 CRUD，并统一后端读取路径，预设 WY/XOM/YUM。

**Architecture:** 新增 `universe_exclude` 服务模块负责 CSV 的读写、软删除与迁移；新增 `/api/universe/excludes` 接口；数据页面增加“全局排除列表”区块并调用该接口。

**Tech Stack:** FastAPI + Pydantic + CSV 文件存储，React + Vite 前端，Playwright 进行 UI 回归。

### Task 1: 后端全局排除清单服务（CSV）

**Files:**
- Create: `backend/app/services/universe_exclude.py`
- Test: `backend/tests/test_universe_excludes_service.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_universe_excludes_service.py
from pathlib import Path
from datetime import datetime

from app.services import universe_exclude


def test_exclude_service_create_and_upsert(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    # create file with defaults
    universe_exclude.ensure_exclude_file(data_root)
    items = universe_exclude.load_exclude_items(data_root, include_disabled=True)
    symbols = {item["symbol"] for item in items}
    assert {"WY", "XOM", "YUM"}.issubset(symbols)

    universe_exclude.upsert_exclude_item(
        data_root, symbol="ABCD", reason="test", source="manual/ui", enabled=True
    )
    active = universe_exclude.load_exclude_symbols(data_root)
    assert "ABCD" in active

    universe_exclude.set_exclude_enabled(data_root, symbol="ABCD", enabled=False)
    active = universe_exclude.load_exclude_symbols(data_root)
    assert "ABCD" not in active
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_universe_excludes_service.py::test_exclude_service_create_and_upsert -v`
Expected: FAIL (module not found).

**Step 3: Write minimal implementation**

```python
# backend/app/services/universe_exclude.py
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable

from app.core.config import settings
from app.services.job_lock import JobLock

CSV_HEADER = ["symbol", "enabled", "reason", "source", "created_at", "updated_at"]
DEFAULT_EXCLUDES = ["WY", "XOM", "YUM"]


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    return Path("/data/share/stock/data")


def exclude_symbols_path(data_root: Path | None = None) -> Path:
    root = data_root or _resolve_data_root()
    return root / "universe" / "exclude_symbols.csv"


def ensure_exclude_file(data_root: Path | None = None) -> Path:
    path = exclude_symbols_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        now = datetime.utcnow().isoformat()
        for symbol in DEFAULT_EXCLUDES:
            writer.writerow([symbol, "true", "global exclude", "manual/ui", now, now])
    return path


def load_exclude_items(data_root: Path | None, include_disabled: bool = False) -> list[dict[str, str]]:
    path = ensure_exclude_file(data_root)
    items: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            enabled = (row.get("enabled") or "").strip().lower() != "false"
            if not include_disabled and not enabled:
                continue
            row["symbol"] = symbol
            row["enabled"] = "true" if enabled else "false"
            items.append(row)
    return items


def load_exclude_symbols(data_root: Path | None) -> set[str]:
    return {item["symbol"] for item in load_exclude_items(data_root, False)}


def upsert_exclude_item(
    data_root: Path | None, *, symbol: str, reason: str, source: str, enabled: bool = True
) -> None:
    lock = JobLock("exclude_symbols", data_root)
    if not lock.acquire():
        raise RuntimeError("exclude_symbols_lock_busy")
    try:
        items = load_exclude_items(data_root, include_disabled=True)
        now = datetime.utcnow().isoformat()
        updated = False
        for row in items:
            if row["symbol"] == symbol.upper():
                row["enabled"] = "true" if enabled else "false"
                row["reason"] = reason
                row["source"] = source
                row["updated_at"] = now
                updated = True
                break
        if not updated:
            items.append(
                {
                    "symbol": symbol.upper(),
                    "enabled": "true" if enabled else "false",
                    "reason": reason,
                    "source": source,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        _write_items(data_root, items)
    finally:
        lock.release()


def set_exclude_enabled(data_root: Path | None, *, symbol: str, enabled: bool) -> None:
    upsert_exclude_item(
        data_root, symbol=symbol, reason="", source="manual/ui", enabled=enabled
    )


def _write_items(data_root: Path | None, items: Iterable[dict[str, str]]) -> None:
    path = ensure_exclude_file(data_root)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for row in items:
            writer.writerow(
                [
                    row.get("symbol", ""),
                    row.get("enabled", "true"),
                    row.get("reason", ""),
                    row.get("source", ""),
                    row.get("created_at", ""),
                    row.get("updated_at", ""),
                ]
            )
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_universe_excludes_service.py::test_exclude_service_create_and_upsert -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/services/universe_exclude.py backend/tests/test_universe_excludes_service.py
git commit -m "feat: add global exclude symbols service"
```

### Task 2: API 接口与 Schema

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/universe.py`
- Test: `backend/tests/test_universe_excludes_api.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_universe_excludes_api.py
from fastapi.testclient import TestClient
from app.main import app


def test_universe_excludes_crud():
    client = TestClient(app)
    res = client.get("/api/universe/excludes")
    assert res.status_code == 200
    items = res.json()["items"]
    assert any(row["symbol"] == "WY" for row in items)

    res = client.post("/api/universe/excludes", json={"symbol": "ZZZ", "reason": "test"})
    assert res.status_code == 200

    res = client.patch("/api/universe/excludes/ZZZ", json={"enabled": False})
    assert res.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_universe_excludes_api.py::test_universe_excludes_crud -v`
Expected: FAIL (404).

**Step 3: Write minimal implementation**

```python
# backend/app/schemas.py
class UniverseExcludeItem(BaseModel):
    symbol: str
    enabled: bool
    reason: str | None = None
    source: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

class UniverseExcludeListOut(BaseModel):
    items: list[UniverseExcludeItem]

class UniverseExcludeUpsertIn(BaseModel):
    symbol: str
    reason: str | None = None
    source: str | None = None
    enabled: bool | None = None

class UniverseExcludePatchIn(BaseModel):
    reason: str | None = None
    source: str | None = None
    enabled: bool | None = None
```

```python
# backend/app/routes/universe.py (新增接口)
from fastapi import HTTPException
from app.schemas import UniverseExcludeListOut, UniverseExcludeItem, UniverseExcludeUpsertIn, UniverseExcludePatchIn
from app.services import universe_exclude

@router.get("/excludes", response_model=UniverseExcludeListOut)
def list_universe_excludes(enabled: bool | None = None) -> UniverseExcludeListOut:
    items = universe_exclude.load_exclude_items(None, include_disabled=enabled is None or enabled)
    if enabled is True:
        items = [row for row in items if row.get("enabled") == "true"]
    out_items = [UniverseExcludeItem(
        symbol=row.get("symbol", ""),
        enabled=row.get("enabled") != "false",
        reason=row.get("reason") or "",
        source=row.get("source") or "",
        created_at=row.get("created_at") or None,
        updated_at=row.get("updated_at") or None,
    ) for row in items]
    return UniverseExcludeListOut(items=out_items)

@router.post("/excludes", response_model=UniverseExcludeItem)
def create_universe_exclude(payload: UniverseExcludeUpsertIn) -> UniverseExcludeItem:
    symbol = payload.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol_invalid")
    universe_exclude.upsert_exclude_item(
        None, symbol=symbol, reason=payload.reason or "", source=payload.source or "manual/ui", enabled=payload.enabled is not False
    )
    items = universe_exclude.load_exclude_items(None, include_disabled=True)
    row = next(item for item in items if item["symbol"] == symbol)
    return UniverseExcludeItem(
        symbol=row["symbol"], enabled=row.get("enabled") != "false", reason=row.get("reason") or "", source=row.get("source") or "", created_at=row.get("created_at"), updated_at=row.get("updated_at"),
    )

@router.patch("/excludes/{symbol}", response_model=UniverseExcludeItem)
def patch_universe_exclude(symbol: str, payload: UniverseExcludePatchIn) -> UniverseExcludeItem:
    symbol = symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol_invalid")
    universe_exclude.upsert_exclude_item(
        None, symbol=symbol, reason=payload.reason or "", source=payload.source or "manual/ui", enabled=payload.enabled is not False
    )
    items = universe_exclude.load_exclude_items(None, include_disabled=True)
    row = next(item for item in items if item["symbol"] == symbol)
    return UniverseExcludeItem(
        symbol=row["symbol"], enabled=row.get("enabled") != "false", reason=row.get("reason") or "", source=row.get("source") or "", created_at=row.get("created_at"), updated_at=row.get("updated_at"),
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_universe_excludes_api.py::test_universe_excludes_crud -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/schemas.py backend/app/routes/universe.py backend/tests/test_universe_excludes_api.py
git commit -m "feat: add universe exclude api"
```

### Task 3: 迁移旧排除与业务读取统一

**Files:**
- Modify: `backend/app/services/ml_runner.py`
- Modify: `backend/app/services/pit_runner.py`
- Modify: `backend/app/routes/datasets.py`
- Modify: `backend/app/services/pretrade_runner.py`
- Test: `backend/tests/test_universe_excludes_merge.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_universe_excludes_merge.py
from pathlib import Path
from app.services import universe_exclude


def test_merge_legacy_excludes(tmp_path: Path):
    data_root = tmp_path / "data"
    (data_root / "universe").mkdir(parents=True)
    legacy = data_root / "universe" / "alpha_exclude_symbols.csv"
    legacy.write_text("symbol,reason\nABC,legacy\n", encoding="utf-8")

    universe_exclude.merge_legacy_excludes(data_root)
    symbols = universe_exclude.load_exclude_symbols(data_root)
    assert "ABC" in symbols
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_universe_excludes_merge.py::test_merge_legacy_excludes -v`
Expected: FAIL (merge_legacy_excludes missing).

**Step 3: Write minimal implementation**

```python
# backend/app/services/universe_exclude.py (新增)
LEGACY_PATHS = [
    "universe/alpha_exclude_symbols.csv",
    "universe/fundamentals_exclude.csv",
    "universe/exclude_symbols.csv",
]

def merge_legacy_excludes(data_root: Path | None) -> int:
    root = data_root or _resolve_data_root()
    ensure_exclude_file(root)
    merged = 0
    symbols: set[str] = set()
    for rel in LEGACY_PATHS:
        path = root / rel
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in text:
            item = line.strip().split(",")[0].upper()
            if item and item != "SYMBOL":
                symbols.add(item)
    for symbol in symbols:
        upsert_exclude_item(root, symbol=symbol, reason="legacy", source="import/legacy", enabled=True)
        merged += 1
    return merged
```

并在以下模块改用 `universe_exclude.load_exclude_symbols()`：
- `ml_runner._load_exclude_symbols`
- `pit_runner` 排除逻辑合并全局排除
- `datasets.py` 原 `alpha_exclude` 写入改为调用全局清单
- `pretrade_runner` 相关 symbol 过滤时合并全局排除

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_universe_excludes_merge.py::test_merge_legacy_excludes -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/services/universe_exclude.py backend/app/services/ml_runner.py backend/app/services/pit_runner.py backend/app/routes/datasets.py backend/app/services/pretrade_runner.py backend/tests/test_universe_excludes_merge.py
git commit -m "feat: unify global exclude usage"
```

### Task 4: 数据页面 UI + i18n

**Files:**
- Modify: `frontend/src/pages/DataPage.tsx`
- Modify: `frontend/src/i18n.tsx`
- (Optional) Modify: `frontend/src/types.ts`

**Step 1: Write the failing test (Playwright)**

```ts
// frontend/tests/data-excludes.spec.ts
import { test, expect } from "@playwright/test";

test("global excludes CRUD", async ({ page }) => {
  await page.goto("/data");
  await expect(page.getByText("全局排除列表")).toBeVisible();
  await page.fill("input[name='exclude-symbol']", "ZZZ");
  await page.click("button:has-text('添加')");
  await expect(page.getByText("ZZZ")).toBeVisible();
});
```

**Step 2: Run test to verify it fails**

Run: `npx playwright test frontend/tests/data-excludes.spec.ts -g "global excludes CRUD"`
Expected: FAIL (UI not present).

**Step 3: Write minimal implementation**
- 在 `DataPage.tsx` 新增区块：表格 + 新增表单 + 启用/禁用按钮
- 新增 API 调用：`GET/POST/PATCH /api/universe/excludes`
- i18n 增加：`data.excludes.title`、`data.excludes.add` 等文案

**Step 4: Run test to verify it passes**

Run: `npx playwright test frontend/tests/data-excludes.spec.ts -g "global excludes CRUD"`
Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/src/pages/DataPage.tsx frontend/src/i18n.tsx frontend/tests/data-excludes.spec.ts
git commit -m "feat: add global exclude list UI"
```

### Task 5: 全量回归与交付

**Step 1: Run backend tests**

Run: `pytest backend/tests/test_universe_excludes_service.py backend/tests/test_universe_excludes_api.py backend/tests/test_universe_excludes_merge.py -q`
Expected: PASS.

**Step 2: Run Playwright**

Run: `npx playwright test frontend/tests/data-excludes.spec.ts -g "global excludes CRUD"`
Expected: PASS.

**Step 3: Commit & Push**

```bash
git status -sb
git add -A
git commit -m "chore: finalize global excludes"
git push -u origin feature/global-exclude-ui
```
