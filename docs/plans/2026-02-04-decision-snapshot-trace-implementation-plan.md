# 决策快照追溯与列表 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在决策快照中建立 backtest_run_id 追溯链路，并在项目页提供快照历史列表与详情展示。

**Architecture:** 后端新增 backtest_run_id 字段与列表 API，生成快照时记录追溯来源；前端在算法页增加输入与历史列表，详情面板可切换显示。

**Tech Stack:** FastAPI, SQLAlchemy, MySQL, React, Vite

---

### Task 1: 决策快照回测追溯规则

**Files:**
- Create: `backend/tests/test_decision_snapshot_backtest_link.py`
- Modify: `backend/app/services/decision_snapshot.py`

**Step 1: Write the failing test**

```python
from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, MLPipelineRun, BacktestRun
from app.services.decision_snapshot import resolve_backtest_run_link


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_resolve_backtest_run_link_prefers_explicit():
    session = _make_session()
    project = Project(name="p1", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    run = BacktestRun(project_id=project.id, status="success")
    session.add(run)
    session.commit()
    session.refresh(run)

    resolved, status = resolve_backtest_run_link(
        session,
        project_id=project.id,
        pipeline_id=None,
        explicit_backtest_run_id=run.id,
    )
    assert resolved == run.id
    assert status == "explicit"
    session.close()


def test_resolve_backtest_run_link_pipeline_then_project():
    session = _make_session()
    project = Project(name="p1", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    pipeline = MLPipelineRun(project_id=project.id, name="pl", status="success")
    session.add(pipeline)
    session.commit()
    session.refresh(pipeline)

    project_run = BacktestRun(project_id=project.id, status="success")
    pipeline_run = BacktestRun(project_id=project.id, pipeline_id=pipeline.id, status="success")
    session.add_all([project_run, pipeline_run])
    session.commit()

    resolved, status = resolve_backtest_run_link(
        session,
        project_id=project.id,
        pipeline_id=pipeline.id,
        explicit_backtest_run_id=None,
    )
    assert resolved == pipeline_run.id
    assert status == "auto_pipeline"

    resolved2, status2 = resolve_backtest_run_link(
        session,
        project_id=project.id,
        pipeline_id=None,
        explicit_backtest_run_id=None,
    )
    assert resolved2 == project_run.id
    assert status2 == "auto_project"
    session.close()


def test_resolve_backtest_run_link_missing():
    session = _make_session()
    project = Project(name="p1", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    resolved, status = resolve_backtest_run_link(
        session,
        project_id=project.id,
        pipeline_id=None,
        explicit_backtest_run_id=None,
    )
    assert resolved is None
    assert status == "missing"
    session.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_decision_snapshot_backtest_link.py -v`
Expected: FAIL (missing resolve_backtest_run_link).

**Step 3: Write minimal implementation**

```python
# backend/app/services/decision_snapshot.py
from app.models import BacktestRun


def resolve_backtest_run_link(session, *, project_id: int, pipeline_id: int | None, explicit_backtest_run_id: int | None):
    if explicit_backtest_run_id:
        run = session.get(BacktestRun, explicit_backtest_run_id)
        if not run:
            raise ValueError("backtest_run_not_found")
        if run.project_id != project_id:
            raise ValueError("backtest_run_project_mismatch")
        return run.id, "explicit"
    if pipeline_id:
        pipeline_run = (
            session.query(BacktestRun)
            .filter(
                BacktestRun.project_id == project_id,
                BacktestRun.pipeline_id == pipeline_id,
                BacktestRun.status == "success",
            )
            .order_by(BacktestRun.created_at.desc())
            .first()
        )
        if pipeline_run:
            return pipeline_run.id, "auto_pipeline"
    project_run = (
        session.query(BacktestRun)
        .filter(
            BacktestRun.project_id == project_id,
            BacktestRun.status == "success",
        )
        .order_by(BacktestRun.created_at.desc())
        .first()
    )
    if project_run:
        return project_run.id, "auto_project"
    return None, "missing"
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_decision_snapshot_backtest_link.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/tests/test_decision_snapshot_backtest_link.py backend/app/services/decision_snapshot.py
git commit -m "test: add backtest link resolver"
```

---

### Task 2: 决策快照列表 API 与模型字段

**Files:**
- Create: `backend/tests/test_decision_snapshot_page.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/decisions.py`
- Create: `deploy/mysql/patches/20260204_decision_snapshot_backtest_run_id.sql`

**Step 1: Write the failing test**

```python
from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, DecisionSnapshot
from app.routes import decisions as decision_routes


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_decision_snapshot_page_filters(monkeypatch):
    session = _make_session()
    project_a = Project(name="p-a", description="")
    project_b = Project(name="p-b", description="")
    session.add_all([project_a, project_b])
    session.commit()
    session.refresh(project_a)
    session.refresh(project_b)

    session.add_all([
        DecisionSnapshot(project_id=project_a.id, status="success", backtest_run_id=11),
        DecisionSnapshot(project_id=project_a.id, status="failed", backtest_run_id=12),
        DecisionSnapshot(project_id=project_b.id, status="success", backtest_run_id=11),
    ])
    session.commit()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(decision_routes, "get_session", _get_session)

    resp = decision_routes.list_decision_snapshots_page(
        project_id=project_a.id,
        page=1,
        page_size=10,
        status="success",
        backtest_run_id=11,
        snapshot_date=None,
        keyword=None,
    )
    dumped = resp.model_dump()
    assert dumped["total"] == 1
    assert dumped["items"][0]["backtest_run_id"] == 11
    session.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_decision_snapshot_page.py -v`
Expected: FAIL (missing field/route).

**Step 3: Write minimal implementation**

```python
# backend/app/models.py (DecisionSnapshot)
backtest_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

```python
# backend/app/schemas.py
class DecisionSnapshotRequest(BaseModel):
    ...
    backtest_run_id: int | None = None

class DecisionSnapshotOut(BaseModel):
    ...
    backtest_run_id: int | None = None

class DecisionSnapshotDetailOut(DecisionSnapshotOut):
    ...

class DecisionSnapshotPreviewOut(BaseModel):
    ...
    backtest_run_id: int | None = None

class DecisionSnapshotListItem(BaseModel):
    id: int
    project_id: int
    status: str
    snapshot_date: str | None = None
    backtest_run_id: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True

class DecisionSnapshotPageOut(BaseModel):
    items: list[DecisionSnapshotListItem]
    total: int
    page: int
    page_size: int
```

```python
# backend/app/routes/decisions.py
@router.get("", response_model=DecisionSnapshotPageOut)
def list_decision_snapshots_page(
    project_id: int = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    status: str | None = None,
    snapshot_date: str | None = None,
    backtest_run_id: int | None = None,
    keyword: str | None = None,
):
    with get_session() as session:
        query = session.query(DecisionSnapshot).filter(DecisionSnapshot.project_id == project_id)
        if status:
            query = query.filter(DecisionSnapshot.status == status)
        if snapshot_date:
            query = query.filter(DecisionSnapshot.snapshot_date == snapshot_date)
        if backtest_run_id is not None:
            query = query.filter(DecisionSnapshot.backtest_run_id == backtest_run_id)
        if keyword:
            like = f"%{keyword}%"
            query = query.filter(
                DecisionSnapshot.id.like(like)
                | DecisionSnapshot.pipeline_id.like(like)
                | DecisionSnapshot.train_job_id.like(like)
            )
        total = query.count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            query.order_by(DecisionSnapshot.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return DecisionSnapshotPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )
```

```sql
-- deploy/mysql/patches/20260204_decision_snapshot_backtest_run_id.sql
-- [DESCRIPTION] add backtest_run_id to decision_snapshots
-- [IMPACT] allow decision snapshot to reference a backtest run
-- [ROLLBACK] manually drop column and index if needed

SET @col_exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'decision_snapshots'
    AND COLUMN_NAME = 'backtest_run_id'
);
SET @sql = IF(@col_exists = 0,
  'ALTER TABLE decision_snapshots ADD COLUMN backtest_run_id INT NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists = (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'decision_snapshots'
    AND INDEX_NAME = 'idx_decision_snapshots_backtest_run_id'
);
SET @sql = IF(@idx_exists = 0,
  'CREATE INDEX idx_decision_snapshots_backtest_run_id ON decision_snapshots (backtest_run_id)',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_decision_snapshot_page.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/tests/test_decision_snapshot_page.py backend/app/models.py backend/app/schemas.py backend/app/routes/decisions.py deploy/mysql/patches/20260204_decision_snapshot_backtest_run_id.sql
git commit -m "feat: add decision snapshot list and backtest field"
```

---

### Task 3: 决策快照运行/预览链路追溯写入

**Files:**
- Modify: `backend/app/routes/decisions.py`
- Modify: `backend/app/services/decision_snapshot.py`
- Modify: `backend/app/services/pretrade_runner.py`
- Modify: `backend/app/services/audit_log.py` (if needed)

**Step 1: Write the failing test**

```python
# backend/tests/test_decision_snapshot_backtest_route.py
from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project
from app.routes import decisions as decision_routes
from app.schemas import DecisionSnapshotRequest


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_decision_snapshot_run_invalid_backtest(monkeypatch):
    session = _make_session()
    project = Project(name="p-a", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(decision_routes, "get_session", _get_session)

    payload = DecisionSnapshotRequest(project_id=project.id, backtest_run_id=9999)
    try:
        decision_routes.run_decision_snapshot(payload, background_tasks=None)
    except Exception as exc:
        assert "backtest_run_not_found" in str(exc)
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_decision_snapshot_backtest_route.py -v`
Expected: FAIL (no validation).

**Step 3: Write minimal implementation**

```python
# backend/app/services/decision_snapshot.py
# update generate_decision_snapshot signature to accept backtest_run_id/link_status
# add backtest_run_id and backtest_link_status to summary_payload
```

```python
# backend/app/routes/decisions.py
# in preview/run, call resolve_backtest_run_link and pass to generate_decision_snapshot
# set snapshot.backtest_run_id
# add backtest_run_id to params + audit detail
```

```python
# backend/app/services/pretrade_runner.py
# when building snapshot params, include backtest_run_id if available
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_decision_snapshot_backtest_route.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/tests/test_decision_snapshot_backtest_route.py backend/app/routes/decisions.py backend/app/services/decision_snapshot.py backend/app/services/pretrade_runner.py
git commit -m "feat: persist decision snapshot backtest link"
```

---

### Task 4: 前端表单 + 历史列表 + 详情面板

**Files:**
- Modify: `frontend/src/pages/ProjectsPage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Modify: `frontend/src/styles.css`

**Step 1: Write the failing test**

手工验证为主（本次不新增前端自动化测试）。

**Step 2: Implement UI**

- 表单新增 `backtest_run_id` 输入并写入 payload。
- 新增“快照历史”列表 + 详情面板切换。
- 详情显示 `backtest_run_id` 与 `backtest_link_status`。

**Step 3: Run build**

Run: `cd frontend && npm run build`
Expected: build success.

**Step 4: Commit**

```bash
git add frontend/src/pages/ProjectsPage.tsx frontend/src/i18n.tsx frontend/src/styles.css
git commit -m "feat: add decision snapshot history UI"
```

---

### Task 5: 验证与回归

**Step 1: Backend tests**

Run: `pytest backend/tests/test_decision_snapshot_backtest_link.py backend/tests/test_decision_snapshot_page.py backend/tests/test_decision_snapshot_backtest_route.py -v`
Expected: PASS.

**Step 2: Manual checks**

- 项目页 → 算法 → 决策快照：输入 backtest_run_id 运行/预览。
- 历史列表出现记录并可切换详情。
- backtest_run_id 为空时显示“未绑定回测”。

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: address decision snapshot trace regressions"
```
