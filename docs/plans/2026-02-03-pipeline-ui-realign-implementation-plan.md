# Pipeline 工作流审计重构 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 按最新设计重构实盘交易 Pipeline：后端输出完整审计事件流，前端呈现阶段泳道/抽屉/高亮与过滤。

**Architecture:** 后端在聚合层统一拼装 Run 列表与事件流 DTO（含 PIT/Backtest/Trade/Audit），实现过滤与排序；前端新增阶段泳道 + 事件抽屉 + 高亮与筛选。保持无 DB 变更。

**Tech Stack:** FastAPI + SQLAlchemy, React + Vite, Vitest, Pytest.

---

### Task 1: 扩展 Pipeline DTO 字段（TDD）

**Files:**
- Modify: `backend/tests/test_pipeline_aggregator.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/pipeline_aggregator.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_pipeline_aggregator.py

def test_pipeline_event_contains_audit_fields():
    session = _make_session()
    run = PreTradeRun(project_id=1, status="failed", message="pretrade_failed")
    session.add(run)
    session.commit()

    detail = build_pipeline_trace(session, trace_id=f"pretrade:{run.id}")
    event = next(item for item in detail["events"] if item["task_type"] == "pretrade_run")
    assert "error_code" in event
    assert "log_path" in event
    assert "params_snapshot" in event
    assert "artifact_paths" in event
    assert "tags" in event
    assert "parent_id" in event
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_aggregator.py::test_pipeline_event_contains_audit_fields -v`
Expected: FAIL (missing keys)

**Step 3: Write minimal implementation**

```python
# backend/app/schemas.py
class PipelineEventOut(BaseModel):
    ...
    error_code: str | None = None
    log_path: str | None = None
    parent_id: str | None = None
    retry_of: str | None = None
    tags: list[str] = []

# backend/app/services/pipeline_aggregator.py
# fill defaults for fields on events
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_aggregator.py::test_pipeline_event_contains_audit_fields -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/tests/test_pipeline_aggregator.py backend/app/schemas.py backend/app/services/pipeline_aggregator.py
git commit -m "feat: extend pipeline event schema"
```

---

### Task 2: Run 列表过滤与完整 trace 支持（TDD）

**Files:**
- Modify: `backend/tests/test_pipeline_aggregator.py`
- Modify: `backend/app/services/pipeline_aggregator.py`
- Modify: `backend/app/routes/pipeline.py`
- Modify: `backend/app/schemas.py`

**Step 1: Write the failing test**

```python
from datetime import datetime, timedelta


def test_list_pipeline_runs_supports_filters():
    session = _make_session()
    base = datetime(2024, 1, 1)
    run1 = PreTradeRun(project_id=1, status="success", created_at=base)
    run2 = TradeRun(project_id=1, status="failed", mode="paper", created_at=base + timedelta(days=1))
    session.add_all([run1, run2])
    session.commit()

    runs = list_pipeline_runs(
        session,
        project_id=1,
        status="failed",
        run_type="trade",
        started_from=base,
        started_to=base + timedelta(days=2),
        keyword="trade",
    )
    assert [item["trace_id"] for item in runs] == ["trade:1"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_aggregator.py::test_list_pipeline_runs_supports_filters -v`
Expected: FAIL (signature mismatch / not filtered)

**Step 3: Write minimal implementation**

```python
# backend/app/services/pipeline_aggregator.py
# list_pipeline_runs(..., status=None, mode=None, run_type=None, started_from=None, started_to=None, keyword=None)
# apply filters on items before return
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_aggregator.py::test_list_pipeline_runs_supports_filters -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/tests/test_pipeline_aggregator.py backend/app/services/pipeline_aggregator.py backend/app/routes/pipeline.py backend/app/schemas.py
git commit -m "feat: add pipeline run filters"
```

---

### Task 3: 事件流补齐 AutoWeekly/PIT/Backtest/TradeFill/Audit（TDD）

**Files:**
- Modify: `backend/tests/test_pipeline_aggregator.py`
- Modify: `backend/app/services/pipeline_aggregator.py`

**Step 1: Write the failing test**

```python
from app.models import AutoWeeklyJob, PitWeeklyJob, PitFundamentalJob, TradeFill, AuditLog


def test_auto_weekly_trace_includes_pit_backtest_and_audit():
    session = _make_session()
    job = AutoWeeklyJob(project_id=1, status="success", pit_weekly_job_id=1, pit_fundamental_job_id=2)
    pit_weekly = PitWeeklyJob(id=1, status="success", log_path="/tmp/pit_weekly.log")
    pit_fund = PitFundamentalJob(id=2, status="success", log_path="/tmp/pit_fund.log")
    session.add_all([job, pit_weekly, pit_fund])
    session.commit()

    detail = build_pipeline_trace(session, trace_id=f"auto:{job.id}")
    task_types = {event["task_type"] for event in detail["events"]}
    assert "auto_weekly" in task_types
    assert "pit_weekly" in task_types
    assert "pit_fundamental" in task_types
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_aggregator.py::test_auto_weekly_trace_includes_pit_backtest_and_audit -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# backend/app/services/pipeline_aggregator.py
# build_pipeline_trace handles trace_id auto: and trade:
# - auto: include auto_weekly + pit jobs + backtest event + audit logs
# - trade: include trade_run + orders + fills + audit logs
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_aggregator.py::test_auto_weekly_trace_includes_pit_backtest_and_audit -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/tests/test_pipeline_aggregator.py backend/app/services/pipeline_aggregator.py
git commit -m "feat: enrich pipeline trace events"
```

---

### Task 4: 前端阶段泳道 + 事件抽屉 + 高亮逻辑（TDD）

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/i18n.tsx`
- Modify: `frontend/src/pages/LiveTradePage.test.ts`

**Step 1: Write the failing test**

```ts
// frontend/src/pages/LiveTradePage.test.ts
it("renders pipeline stage lanes and event drawer", () => {
  const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
  expect(html).toContain("pipeline-stage-lanes");
  expect(html).toContain("pipeline-event-drawer");
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- LiveTradePage.test.ts`
Expected: FAIL (missing elements)

**Step 3: Write minimal implementation**

```tsx
// LiveTradePage.tsx
// render stage lanes container + drawer container with placeholder
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- LiveTradePage.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/styles.css frontend/src/i18n.tsx frontend/src/pages/LiveTradePage.test.ts
git commit -m "feat: add pipeline stage lanes and drawer"
```

---

### Task 5: 前端过滤器/高亮行为与 API 对齐（TDD）

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/pages/LiveTradePage.test.ts`
- Modify: `frontend/src/i18n.tsx`

**Step 1: Write the failing test**

```ts
it("filters pipeline runs by keyword and highlights events", () => {
  const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
  expect(html).toContain("pipeline-keyword-input");
  expect(html).toContain("pipeline-event-highlight");
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- LiveTradePage.test.ts`
Expected: FAIL

**Step 3: Write minimal implementation**

```tsx
// LiveTradePage.tsx
// add keyword input + highlight class on matched events (by tags)
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- LiveTradePage.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/pages/LiveTradePage.test.ts frontend/src/i18n.tsx
git commit -m "feat: add pipeline filters and highlight"
```

---

### Task 6: 统一回归验证（含前端 build + 重启）

**Step 1: Backend tests**

Run: `pytest tests/test_pipeline_aggregator.py -v`
Expected: PASS

**Step 2: Frontend tests**

Run: `cd frontend && npm run test -- LiveTradePage.test.ts`
Expected: PASS

**Step 3: Frontend build & restart (mandatory)**

Run: `cd frontend && npm run build`
Run: `systemctl --user restart stocklean-frontend`
Expected: build success, service restarted

**Step 4: Commit any remaining changes**

```bash
git status -sb
```
