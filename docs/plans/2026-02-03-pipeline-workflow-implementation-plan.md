# Pipeline 工作流审计 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在实盘交易页新增 Pipeline 子标签与后端聚合 API，实现按项目范围的审计时间轴与事件流。

**Architecture:** 后端新增聚合服务从现有表拼装事件流（AutoWeekly/PreTrade/DecisionSnapshot/TradeRun/AuditLog），不改库；前端新增 Pipeline 子标签与双栏视图，调用聚合 API 渲染阶段泳道与事件列表，并映射重试入口到现有接口。

**Tech Stack:** FastAPI + SQLAlchemy, React + Vite, Vitest, Pytest.

---

### Task 1: 新增后端聚合服务的最小列表能力（TDD）

**Files:**
- Create: `backend/app/services/pipeline_aggregator.py`
- Create: `backend/tests/test_pipeline_aggregator.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_pipeline_aggregator.py
from pathlib import Path
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, PreTradeRun, TradeRun
from app.services.pipeline_aggregator import list_pipeline_runs


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_list_pipeline_runs_project_scoped():
    session = _make_session()
    session.add_all([
        PreTradeRun(project_id=1, status="success"),
        PreTradeRun(project_id=2, status="success"),
        TradeRun(project_id=1, status="queued", mode="paper", params={"source": "manual"}),
    ])
    session.commit()

    runs = list_pipeline_runs(session, project_id=1)
    trace_ids = {item["trace_id"] for item in runs}
    assert "pretrade:1" in trace_ids
    assert "trade:1" in trace_ids
    assert all(item["project_id"] == 1 for item in runs)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_aggregator.py::test_list_pipeline_runs_project_scoped -v`
Expected: FAIL (import error or missing function)

**Step 3: Write minimal implementation**

```python
# backend/app/services/pipeline_aggregator.py
from __future__ import annotations

from typing import Any

from app.models import PreTradeRun, TradeRun


def list_pipeline_runs(session, *, project_id: int) -> list[dict[str, Any]]:
    pretrade_runs = (
        session.query(PreTradeRun)
        .filter(PreTradeRun.project_id == project_id)
        .order_by(PreTradeRun.created_at.desc())
        .all()
    )
    trade_runs = (
        session.query(TradeRun)
        .filter(TradeRun.project_id == project_id)
        .order_by(TradeRun.created_at.desc())
        .all()
    )
    items: list[dict[str, Any]] = []
    for run in pretrade_runs:
        items.append(
            {
                "trace_id": f"pretrade:{run.id}",
                "run_type": "pretrade",
                "project_id": run.project_id,
                "status": run.status,
                "started_at": run.started_at,
                "ended_at": run.ended_at,
                "created_at": run.created_at,
            }
        )
    for run in trade_runs:
        if (run.params or {}).get("pretrade_run_id"):
            continue
        items.append(
            {
                "trace_id": f"trade:{run.id}",
                "run_type": "trade",
                "project_id": run.project_id,
                "status": run.status,
                "mode": run.mode,
                "started_at": run.started_at,
                "ended_at": run.ended_at,
                "created_at": run.created_at,
            }
        )
    return items
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_aggregator.py::test_list_pipeline_runs_project_scoped -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/pipeline_aggregator.py backend/tests/test_pipeline_aggregator.py
git commit -m "feat: add minimal pipeline runs aggregator"
```

---

### Task 2: 完善列表聚合（自动化周任务 + 过滤/排序字段）

**Files:**
- Modify: `backend/app/services/pipeline_aggregator.py`
- Modify: `backend/tests/test_pipeline_aggregator.py`

**Step 1: Write the failing test**

```python
from app.models import AutoWeeklyJob


def test_list_includes_auto_weekly():
    session = _make_session()
    session.add(AutoWeeklyJob(project_id=1, status="running"))
    session.commit()

    runs = list_pipeline_runs(session, project_id=1)
    assert any(item["trace_id"].startswith("auto:") for item in runs)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_aggregator.py::test_list_includes_auto_weekly -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
from app.models import AutoWeeklyJob

# in list_pipeline_runs
weekly_jobs = (
    session.query(AutoWeeklyJob)
    .filter(AutoWeeklyJob.project_id == project_id)
    .order_by(AutoWeeklyJob.created_at.desc())
    .all()
)
for job in weekly_jobs:
    items.append(
        {
            "trace_id": f"auto:{job.id}",
            "run_type": "auto_weekly",
            "project_id": job.project_id,
            "status": job.status,
            "started_at": job.started_at,
            "ended_at": job.ended_at,
            "created_at": job.created_at,
        }
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_aggregator.py::test_list_includes_auto_weekly -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/pipeline_aggregator.py backend/tests/test_pipeline_aggregator.py
git commit -m "feat: include auto weekly jobs in pipeline runs"
```

---

### Task 3: 实现 Trace 详情聚合（PreTrade → Snapshot → TradeRun）

**Files:**
- Modify: `backend/app/services/pipeline_aggregator.py`
- Modify: `backend/tests/test_pipeline_aggregator.py`

**Step 1: Write the failing test**

```python
from app.models import DecisionSnapshot, PreTradeStep, TradeOrder
from app.services.pipeline_aggregator import build_pipeline_trace


def test_pretrade_trace_includes_snapshot_and_trade():
    session = _make_session()
    run = PreTradeRun(project_id=1, status="success")
    session.add(run)
    session.commit()

    snapshot = DecisionSnapshot(project_id=1, status="success")
    session.add(snapshot)
    session.commit()

    trade_run = TradeRun(project_id=1, decision_snapshot_id=snapshot.id, status="queued", mode="paper")
    session.add(trade_run)
    session.commit()

    step = PreTradeStep(
        run_id=run.id,
        step_key="decision_snapshot",
        step_order=1,
        status="success",
        artifacts={"decision_snapshot_id": snapshot.id, "trade_run_id": trade_run.id},
    )
    session.add(step)
    session.commit()

    order = TradeOrder(
        run_id=trade_run.id,
        client_order_id="run-1-SPY-BUY",
        symbol="SPY",
        side="BUY",
        quantity=1,
        order_type="MKT",
        status="NEW",
    )
    session.add(order)
    session.commit()

    detail = build_pipeline_trace(session, trace_id=f"pretrade:{run.id}")
    event_types = {event["task_type"] for event in detail["events"]}
    assert "pretrade_run" in event_types
    assert "pretrade_step" in event_types
    assert "decision_snapshot" in event_types
    assert "trade_run" in event_types
    assert "trade_order" in event_types
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_aggregator.py::test_pretrade_trace_includes_snapshot_and_trade -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# backend/app/services/pipeline_aggregator.py
from app.models import DecisionSnapshot, PreTradeRun, PreTradeStep, TradeOrder, TradeRun


def build_pipeline_trace(session, *, trace_id: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    if trace_id.startswith("pretrade:"):
        run_id = int(trace_id.split(":", 1)[1])
        run = session.get(PreTradeRun, run_id)
        if not run:
            return {"trace_id": trace_id, "events": [], "warnings": ["pretrade_run_missing"]}
        events.append(
            {
                "event_id": f"pretrade_run:{run.id}",
                "task_type": "pretrade_run",
                "task_id": run.id,
                "stage": "pretrade_gate",
                "status": run.status,
                "started_at": run.started_at,
                "ended_at": run.ended_at,
                "message": run.message,
            }
        )
        steps = (
            session.query(PreTradeStep)
            .filter(PreTradeStep.run_id == run.id)
            .order_by(PreTradeStep.step_order.asc())
            .all()
        )
        snapshot_id = None
        trade_run_id = None
        for step in steps:
            events.append(
                {
                    "event_id": f"pretrade_step:{step.id}",
                    "task_type": "pretrade_step",
                    "task_id": step.id,
                    "stage": "pretrade_gate",
                    "status": step.status,
                    "started_at": step.started_at,
                    "ended_at": step.ended_at,
                    "message": step.message,
                    "params_snapshot": step.params,
                    "artifact_paths": step.artifacts,
                }
            )
            if isinstance(step.artifacts, dict):
                snapshot_id = snapshot_id or step.artifacts.get("decision_snapshot_id")
                trade_run_id = trade_run_id or step.artifacts.get("trade_run_id")
        if snapshot_id:
            snapshot = session.get(DecisionSnapshot, int(snapshot_id))
            if snapshot:
                events.append(
                    {
                        "event_id": f"decision_snapshot:{snapshot.id}",
                        "task_type": "decision_snapshot",
                        "task_id": snapshot.id,
                        "stage": "decision_snapshot",
                        "status": snapshot.status,
                        "started_at": snapshot.started_at,
                        "ended_at": snapshot.ended_at,
                        "message": snapshot.message,
                        "artifact_paths": {
                            "summary": snapshot.summary_path,
                            "items": snapshot.items_path,
                            "filters": snapshot.filters_path,
                        },
                    }
                )
            else:
                warnings.append("decision_snapshot_missing")
        if trade_run_id:
            trade_run = session.get(TradeRun, int(trade_run_id))
            if trade_run:
                events.append(
                    {
                        "event_id": f"trade_run:{trade_run.id}",
                        "task_type": "trade_run",
                        "task_id": trade_run.id,
                        "stage": "trade_execute",
                        "status": trade_run.status,
                        "started_at": trade_run.started_at,
                        "ended_at": trade_run.ended_at,
                        "message": trade_run.message,
                        "params_snapshot": trade_run.params,
                    }
                )
                orders = (
                    session.query(TradeOrder)
                    .filter(TradeOrder.run_id == trade_run.id)
                    .order_by(TradeOrder.created_at.asc())
                    .all()
                )
                for order in orders:
                    events.append(
                        {
                            "event_id": f"trade_order:{order.id}",
                            "task_type": "trade_order",
                            "task_id": order.id,
                            "stage": "trade_execute",
                            "status": order.status,
                            "started_at": order.created_at,
                            "ended_at": order.updated_at,
                        }
                    )
            else:
                warnings.append("trade_run_missing")
        return {"trace_id": trace_id, "events": events, "warnings": warnings}
    return {"trace_id": trace_id, "events": [], "warnings": ["trace_type_unknown"]}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_aggregator.py::test_pretrade_trace_includes_snapshot_and_trade -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/pipeline_aggregator.py backend/tests/test_pipeline_aggregator.py
git commit -m "feat: build pipeline trace for pretrade"
```

---

### Task 4: 增加后端 Schema + 路由 API

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/routes/pipeline.py`
- Modify: `backend/app/main.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_pipeline_routes.py
from pathlib import Path
import sys
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app


def test_pipeline_runs_requires_project_id():
    client = TestClient(app)
    resp = client.get("/api/pipeline/runs")
    assert resp.status_code == 422
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_routes.py::test_pipeline_runs_requires_project_id -v`
Expected: FAIL (route missing)

**Step 3: Write minimal implementation**

```python
# backend/app/routes/pipeline.py
from fastapi import APIRouter, Query
from app.db import get_session
from app.services.pipeline_aggregator import list_pipeline_runs, build_pipeline_trace
from app.schemas import PipelineRunListOut, PipelineRunDetailOut

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.get("/runs", response_model=list[PipelineRunListOut])
def list_runs(project_id: int = Query(...)):
    with get_session() as session:
        return list_pipeline_runs(session, project_id=project_id)


@router.get("/runs/{trace_id}", response_model=PipelineRunDetailOut)
def get_trace(trace_id: str):
    with get_session() as session:
        return build_pipeline_trace(session, trace_id=trace_id)
```

```python
# backend/app/schemas.py
class PipelineRunListOut(BaseModel):
    trace_id: str
    run_type: str
    project_id: int
    status: str
    mode: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class PipelineEventOut(BaseModel):
    event_id: str
    task_type: str
    task_id: int | None = None
    stage: str | None = None
    status: str | None = None
    message: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    params_snapshot: dict | None = None
    artifact_paths: dict | None = None


class PipelineRunDetailOut(BaseModel):
    trace_id: str
    events: list[PipelineEventOut]
    warnings: list[str] = []
```

```python
# backend/app/main.py
from app.routes import pipeline
app.include_router(pipeline.router)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_routes.py::test_pipeline_runs_requires_project_id -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/routes/pipeline.py backend/app/schemas.py backend/app/main.py backend/tests/test_pipeline_routes.py
git commit -m "feat: add pipeline routes and schemas"
```

---

### Task 5: 前端 i18n + Pipeline Tab 标题占位

**Files:**
- Modify: `frontend/src/i18n.tsx`
- Modify: `frontend/src/pages/LiveTradePage.test.ts`

**Step 1: Write the failing test**

```tsx
// frontend/src/pages/LiveTradePage.test.ts
it("renders pipeline tab", () => {
  const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
  expect(html).toContain("trade.pipelineTab");
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- LiveTradePage.test.ts`
Expected: FAIL (missing key)

**Step 3: Write minimal implementation**

```tsx
// frontend/src/i18n.tsx (zh)
trade: {
  pipelineTab: "Pipeline",
  pipelineTitle: "交易 Pipeline",
  pipelineMeta: "按项目回放自动/手动链路",
}
```

```tsx
// frontend/src/i18n.tsx (en)
trade: {
  pipelineTab: "Pipeline",
  pipelineTitle: "Pipeline",
  pipelineMeta: "Replay the workflow by project",
}
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- LiveTradePage.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/i18n.tsx frontend/src/pages/LiveTradePage.test.ts
git commit -m "feat: add pipeline tab i18n"
```

---

### Task 6: LiveTradePage 新增 Pipeline 子标签骨架

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/styles.css`

**Step 1: Write the failing test**

```tsx
// frontend/src/pages/LiveTradePage.test.ts
it("renders pipeline view container", () => {
  const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
  expect(html).toContain("pipeline-view");
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- LiveTradePage.test.ts`
Expected: FAIL

**Step 3: Write minimal implementation**

```tsx
// LiveTradePage.tsx
const [mainTab, setMainTab] = useState<"overview" | "pipeline">("overview");

<div className="project-tabs">
  <button className={mainTab === "overview" ? "tab-button active" : "tab-button"} onClick={() => setMainTab("overview")}>
    {t("trade.mainSectionTitle")}
  </button>
  <button className={mainTab === "pipeline" ? "tab-button active" : "tab-button"} onClick={() => setMainTab("pipeline")}>
    {t("trade.pipelineTab")}
  </button>
</div>

{mainTab === "pipeline" ? (
  <div className="pipeline-view">...</div>
) : (
  <>现有内容</>
)}
```

```css
/* styles.css */
.pipeline-view {
  margin-top: 12px;
  display: grid;
  grid-template-columns: minmax(260px, 320px) 1fr;
  gap: 16px;
}
.pipeline-view .pipeline-list {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px;
}
.pipeline-view .pipeline-detail {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px;
  min-height: 300px;
}
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- LiveTradePage.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/styles.css frontend/src/pages/LiveTradePage.test.ts
git commit -m "feat: add pipeline tab skeleton"
```

---

### Task 7: Pipeline 列表与详情数据获取 + UI

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`

**Step 1: Write the failing test**

```tsx
// LiveTradePage.test.ts
it("renders pipeline filters labels", () => {
  const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
  expect(html).toContain("trade.pipeline.filters.project");
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- LiveTradePage.test.ts`
Expected: FAIL

**Step 3: Write minimal implementation**

```tsx
// LiveTradePage.tsx
interface PipelineRunItem { trace_id: string; run_type: string; project_id: number; status: string; mode?: string | null; created_at?: string | null; }
interface PipelineEvent { event_id: string; task_type: string; task_id?: number | null; stage?: string | null; status?: string | null; message?: string | null; started_at?: string | null; ended_at?: string | null; }
interface PipelineTraceDetail { trace_id: string; events: PipelineEvent[]; warnings?: string[]; }

const [pipelineProjectId, setPipelineProjectId] = useState<string>("");
const [pipelineRuns, setPipelineRuns] = useState<PipelineRunItem[]>([]);
const [pipelineRunsLoading, setPipelineRunsLoading] = useState(false);
const [pipelineRunsError, setPipelineRunsError] = useState("");
const [pipelineTraceId, setPipelineTraceId] = useState<string | null>(null);
const [pipelineDetail, setPipelineDetail] = useState<PipelineTraceDetail | null>(null);

const loadPipelineRuns = async () => { /* call /api/pipeline/runs with project_id */ };
const loadPipelineDetail = async (traceId: string) => { /* call /api/pipeline/runs/{trace_id} */ };
```

```tsx
// i18n.tsx
trade: {
  pipeline: {
    filters: {
      project: "项目",
      status: "状态",
      type: "类型",
      keyword: "关键 ID",
    },
    listTitle: "运行列表",
    detailTitle: "事件流",
    empty: "暂无 Pipeline 运行",
  },
}
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- LiveTradePage.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx frontend/src/pages/LiveTradePage.test.ts
git commit -m "feat: load pipeline runs and detail"
```

---

### Task 8: 事件时间轴与重试入口（UI 侧）

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/styles.css`

**Step 1: Write the failing test**

```tsx
// LiveTradePage.test.ts
it("renders pipeline event list", () => {
  const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
  expect(html).toContain("pipeline-events");
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- LiveTradePage.test.ts`
Expected: FAIL

**Step 3: Write minimal implementation**

```tsx
// LiveTradePage.tsx
<div className="pipeline-events">
  {pipelineDetail?.events?.map((event) => (
    <div key={event.event_id} className={`pipeline-event ${event.status || ""}`}>
      <div className="pipeline-event-title">{event.task_type}</div>
      <div className="pipeline-event-meta">{event.message || t("common.none")}</div>
    </div>
  ))}
</div>
```

```css
.pipeline-events { display: grid; gap: 8px; margin-top: 12px; }
.pipeline-event { border: 1px solid var(--border); border-radius: 10px; padding: 10px; background: var(--panel-alt); }
.pipeline-event-title { font-weight: 600; }
.pipeline-event-meta { font-size: 12px; color: var(--muted); }
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- LiveTradePage.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/styles.css frontend/src/pages/LiveTradePage.test.ts
git commit -m "feat: render pipeline events"
```

---

### Task 9: 前端构建与服务重启（强制）

**Files:**
- None (build + restart)

**Step 1: Build frontend**

Run: `cd frontend && npm run build`
Expected: build success

**Step 2: Restart frontend service**

Run: `systemctl --user restart stocklean-frontend`
Expected: no error

**Step 3: Commit (if build output tracked)**

```bash
git status --short
```
Expected: no tracked build artifacts

---

### Task 10: 回归测试（后端 + 前端）

**Files:**
- None

**Step 1: Backend tests**

Run: `cd backend && pytest tests/test_pipeline_aggregator.py tests/test_pipeline_routes.py -v`
Expected: PASS

**Step 2: Frontend tests**

Run: `cd frontend && npm run test -- LiveTradePage.test.ts`
Expected: PASS

**Step 3: Commit**

```bash
git status --short
```
Expected: clean
