# 数据页分页 + PreTrade 取消堆积修复 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 给 Data 页面 PIT 周度/财报/PreTrade 历史增加分页（默认 10 条/页），并修复 PreTrade 取消后长期处于“取消中”的问题。

**Architecture:** 后端新增 page 接口返回 `Paginated` 结构，前端 DataPage 接入 `PaginationBar`；PreTrade 取消流程在后端落盘状态与 steps 终态对齐。

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic, React + Vite + Playwright.

---

### Task 0: 提交设计文档

**Files:**
- Add: `docs/plans/2026-01-26-data-pretrade-pagination-design.md`

**Step 1: Stage design doc**

Run: `git add docs/plans/2026-01-26-data-pretrade-pagination-design.md`

**Step 2: Commit**

```bash
git commit -m "docs: add data page pagination design"
```

---

### Task 1: 新增 PIT 周度分页接口与测试

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/pit.py`
- Test: `backend/tests/test_pit_pagination.py`

**Step 1: Write the failing test**

Create `backend/tests/test_pit_pagination.py`:

```python
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, PitWeeklyJob, PitFundamentalJob
from app.routes import pit as pit_routes


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_pit_weekly_jobs_page(monkeypatch):
    session = _make_session()

    for idx in range(12):
        session.add(PitWeeklyJob(status="queued", params={"i": idx}))
    session.commit()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(pit_routes, "get_session", _get_session)

    resp = pit_routes.list_weekly_jobs_page(page=2, page_size=5)
    dumped = resp.model_dump()
    assert dumped["total"] == 12
    assert dumped["page"] == 2
    assert dumped["page_size"] == 5
    assert len(dumped["items"]) == 5

    session.close()
```

**Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_pit_pagination.py::test_pit_weekly_jobs_page -q`

Expected: FAIL (route function missing / schema missing).

**Step 3: Write minimal implementation**

Add schema in `backend/app/schemas.py`:

```python
class PitWeeklyJobPageOut(BaseModel):
    items: list[PitWeeklyJobOut]
    total: int
    page: int
    page_size: int
```

Add route in `backend/app/routes/pit.py`:

```python
MAX_PAGE_SIZE = 200

def _coerce_pagination(page: int, page_size: int, total: int) -> tuple[int, int, int]:
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
    safe_page = min(max(page, 1), total_pages)
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset

@router.get("/weekly-jobs/page", response_model=PitWeeklyJobPageOut)
def list_weekly_jobs_page(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=MAX_PAGE_SIZE)):
    with get_session() as session:
        total = session.query(PitWeeklyJob).count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            session.query(PitWeeklyJob)
            .order_by(PitWeeklyJob.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return PitWeeklyJobPageOut(items=items, total=total, page=safe_page, page_size=safe_page_size)
```

**Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_pit_pagination.py::test_pit_weekly_jobs_page -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/schemas.py backend/app/routes/pit.py backend/tests/test_pit_pagination.py
git commit -m "feat(pit): add weekly jobs pagination"
```

---

### Task 2: PIT 财报分页接口与测试

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/pit.py`
- Test: `backend/tests/test_pit_pagination.py`

**Step 1: Write the failing test**

Append to `backend/tests/test_pit_pagination.py`:

```python
def test_pit_fundamental_jobs_page(monkeypatch):
    session = _make_session()

    for idx in range(9):
        session.add(PitFundamentalJob(status="queued", params={"i": idx}))
    session.commit()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(pit_routes, "get_session", _get_session)

    resp = pit_routes.list_fundamental_jobs_page(page=1, page_size=4)
    dumped = resp.model_dump()
    assert dumped["total"] == 9
    assert dumped["page"] == 1
    assert dumped["page_size"] == 4
    assert len(dumped["items"]) == 4

    session.close()
```

**Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_pit_pagination.py::test_pit_fundamental_jobs_page -q`

Expected: FAIL (route/schema missing).

**Step 3: Write minimal implementation**

Add schema in `backend/app/schemas.py`:

```python
class PitFundamentalJobPageOut(BaseModel):
    items: list[PitFundamentalJobOut]
    total: int
    page: int
    page_size: int
```

Add route in `backend/app/routes/pit.py`:

```python
@router.get("/fundamental-jobs/page", response_model=PitFundamentalJobPageOut)
def list_fundamental_jobs_page(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=MAX_PAGE_SIZE)):
    with get_session() as session:
        total = session.query(PitFundamentalJob).count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            session.query(PitFundamentalJob)
            .order_by(PitFundamentalJob.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return PitFundamentalJobPageOut(items=items, total=total, page=safe_page, page_size=safe_page_size)
```

**Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_pit_pagination.py::test_pit_fundamental_jobs_page -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/schemas.py backend/app/routes/pit.py backend/tests/test_pit_pagination.py
git commit -m "feat(pit): add fundamental jobs pagination"
```

---

### Task 3: PreTrade 运行历史分页接口与测试

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/pretrade.py`
- Test: `backend/tests/test_pretrade_runs_page.py`

**Step 1: Write the failing test**

Create `backend/tests/test_pretrade_runs_page.py`:

```python
from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, PreTradeRun, Project
from app.routes import pretrade as pretrade_routes


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_pretrade_runs_page_filters_project(monkeypatch):
    session = _make_session()

    project_a = Project(name="p-a", description="")
    project_b = Project(name="p-b", description="")
    session.add_all([project_a, project_b])
    session.commit()
    session.refresh(project_a)
    session.refresh(project_b)

    for _ in range(7):
        session.add(PreTradeRun(project_id=project_a.id, status="queued"))
    for _ in range(3):
        session.add(PreTradeRun(project_id=project_b.id, status="queued"))
    session.commit()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(pretrade_routes, "get_session", _get_session)

    resp = pretrade_routes.list_pretrade_runs_page(project_id=project_a.id, page=1, page_size=5)
    dumped = resp.model_dump()
    assert dumped["total"] == 7
    assert dumped["page_size"] == 5
    assert len(dumped["items"]) == 5

    session.close()
```

**Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_pretrade_runs_page.py::test_pretrade_runs_page_filters_project -q`

Expected: FAIL (route/schema missing).

**Step 3: Write minimal implementation**

Add schema in `backend/app/schemas.py`:

```python
class PreTradeRunPageOut(BaseModel):
    items: list[PreTradeRunOut]
    total: int
    page: int
    page_size: int
```

Add route in `backend/app/routes/pretrade.py`:

```python
MAX_PAGE_SIZE = 200

def _coerce_pagination(page: int, page_size: int, total: int) -> tuple[int, int, int]:
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
    safe_page = min(max(page, 1), total_pages)
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset

@router.get("/runs/page", response_model=PreTradeRunPageOut)
def list_pretrade_runs_page(
    project_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        query = session.query(PreTradeRun)
        if project_id:
            query = query.filter(PreTradeRun.project_id == project_id)
        total = query.count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            query.order_by(PreTradeRun.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return PreTradeRunPageOut(items=items, total=total, page=safe_page, page_size=safe_page_size)
```

**Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_pretrade_runs_page.py::test_pretrade_runs_page_filters_project -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/schemas.py backend/app/routes/pretrade.py backend/tests/test_pretrade_runs_page.py
git commit -m "feat(pretrade): add runs pagination"
```

---

### Task 4: 修复 PreTrade 取消堆积逻辑（TDD）

**Files:**
- Modify: `backend/app/routes/pretrade.py`
- Test: `backend/tests/test_pretrade_cancel.py`

**Step 1: Write the failing tests**

Create `backend/tests/test_pretrade_cancel.py`:

```python
from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, PreTradeRun, PreTradeStep, Project
from app.routes import pretrade as pretrade_routes


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_pretrade_cancel_queued_marks_canceled(monkeypatch):
    session = _make_session()

    project = Project(name="p", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    run = PreTradeRun(project_id=project.id, status="queued")
    session.add(run)
    session.commit()
    session.refresh(run)

    step = PreTradeStep(run_id=run.id, step_key="x", step_order=0, status="queued")
    session.add(step)
    session.commit()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(pretrade_routes, "get_session", _get_session)

    resp = pretrade_routes.cancel_pretrade_run(run.id)
    assert resp.status == "canceled"

    refreshed = session.get(PreTradeRun, run.id)
    assert refreshed.status == "canceled"
    steps = session.query(PreTradeStep).filter(PreTradeStep.run_id == run.id).all()
    assert all(step.status == "canceled" for step in steps)

    session.close()


def test_pretrade_cancel_requested_normalized_on_detail(monkeypatch):
    session = _make_session()

    project = Project(name="p2", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    run = PreTradeRun(project_id=project.id, status="cancel_requested")
    session.add(run)
    session.commit()
    session.refresh(run)

    step = PreTradeStep(run_id=run.id, step_key="x", step_order=0, status="success")
    session.add(step)
    session.commit()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(pretrade_routes, "get_session", _get_session)

    resp = pretrade_routes.get_pretrade_run(run.id)
    assert resp.run.status == "canceled"

    session.close()
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_pretrade_cancel.py::test_pretrade_cancel_queued_marks_canceled -q`

Expected: FAIL (queued cancel not turning to canceled).

**Step 3: Write minimal implementation**

In `backend/app/routes/pretrade.py`:
- Update `cancel_pretrade_run` to:
  - If `status == queued`: set `run.status = "canceled"`, `run.message = "canceled"`, `run.ended_at = now`.
  - Bulk update steps to `canceled` with `message="run_canceled"` and `ended_at=now`.
  - Return updated run.
- Add helper `_normalize_canceled_run(session, run)` that:
  - If `run.status == cancel_requested` and all steps in terminal statuses (`success/failed/skipped/canceled`), set run to `canceled` with message/ended_at.
- Call helper inside `get_pretrade_run` (and optionally `list_pretrade_runs_page`) before building response.

**Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_pretrade_cancel.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/routes/pretrade.py backend/tests/test_pretrade_cancel.py
git commit -m "fix(pretrade): finalize cancel state"
```

---

### Task 5: DataPage 接入分页（PIT 周度/财报/PreTrade）

**Files:**
- Modify: `frontend/src/pages/DataPage.tsx`
- Test: `frontend/tests/data-page-pagination.spec.ts`

**Step 1: Write the failing test (Playwright)**

Create `frontend/tests/data-page-pagination.spec.ts`:

```typescript
import { test, expect } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL || "http://127.0.0.1:4173";

test("data page shows pagination bars for PIT and PreTrade", async ({ page }) => {
  await page.goto(`${BASE_URL}/data`);
  await expect(page.getByText("PIT 周度任务")).toBeVisible();
  await expect(page.getByText("PIT 财报任务")).toBeVisible();
  await expect(page.getByText("PreTrade 周度检查")).toBeVisible();

  const paginations = page.locator(".pagination");
  await expect(paginations).toHaveCount(3);
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && E2E_BASE_URL=http://192.168.1.31:8081 npx playwright test tests/data-page-pagination.spec.ts`

Expected: FAIL (pagination bars missing).

**Step 3: Write minimal implementation**

In `frontend/src/pages/DataPage.tsx`:
- 增加 state：
  - `pitWeeklyPage/pitWeeklyPageSize/pitWeeklyTotal`
  - `pitFundPage/pitFundPageSize/pitFundTotal`
  - `pretradeRunsPage/pretradeRunsPageSize/pretradeRunsTotal`
  - 将 `bulkHistoryPageSize` 默认值改为 `10`.
- 修改 `loadPitWeeklyJobs/loadPitFundJobs/loadPretradeRuns` 使用新 page 接口并写入 total。
- 在三张历史表格下方添加 `PaginationBar`，默认 `pageSize=10`，翻页时重载对应列表。

**Step 4: Run test to verify it passes**

Run: `cd frontend && E2E_BASE_URL=http://192.168.1.31:8081 npx playwright test tests/data-page-pagination.spec.ts`

Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/src/pages/DataPage.tsx frontend/tests/data-page-pagination.spec.ts
git commit -m "feat(frontend): paginate data page histories"
```

---

### Task 6: 集成回归测试

**Files:**
- None

**Step 1: Run backend tests**

Run: `cd backend && pytest tests/test_pit_pagination.py tests/test_pretrade_runs_page.py tests/test_pretrade_cancel.py -q`

Expected: PASS.

**Step 2: Run frontend unit tests**

Run: `cd frontend && npm run test`

Expected: PASS.

**Step 3: Run Playwright**

Run: `cd frontend && E2E_BASE_URL=http://192.168.1.31:8081 npx playwright test tests/data-page-pagination.spec.ts`

Expected: PASS.

**Step 4: Commit**

No commit (verification only).
```
