# Pipeline 工作流审计修复 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 Pipeline 时间轴按项目展示的关键问题（排序与可操作性），保持 API 形状不变。

**Architecture:** 后端在聚合层完成跨类型排序与事件流按时间排序；前端提取 trace_id 解析工具并修复 pretrade 解析。无数据库变更。

**Tech Stack:** FastAPI + SQLAlchemy, React + Vite, Vitest, Pytest.

---

### Task 1: 后端 Run 列表按时间倒序排序（TDD）

**Files:**
- Modify: `backend/tests/test_pipeline_aggregator.py`
- Modify: `backend/app/services/pipeline_aggregator.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_pipeline_aggregator.py
from datetime import datetime


def test_list_pipeline_runs_sorted_desc():
    session = _make_session()
    session.add_all(
        [
            PreTradeRun(project_id=1, status="success", created_at=datetime(2024, 1, 1)),
            TradeRun(
                project_id=1,
                status="queued",
                mode="paper",
                created_at=datetime(2024, 1, 2),
            ),
            AutoWeeklyJob(project_id=1, status="running", created_at=datetime(2024, 1, 3)),
        ]
    )
    session.commit()

    runs = list_pipeline_runs(session, project_id=1)
    assert [item["trace_id"] for item in runs] == ["auto:1", "trade:1", "pretrade:1"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_aggregator.py::test_list_pipeline_runs_sorted_desc -v`
Expected: FAIL (order mismatch)

**Step 3: Write minimal implementation**

```python
# backend/app/services/pipeline_aggregator.py
items.sort(key=_run_sort_key, reverse=True)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_aggregator.py::test_list_pipeline_runs_sorted_desc -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/tests/test_pipeline_aggregator.py backend/app/services/pipeline_aggregator.py
git commit -m "fix: sort pipeline runs by created_at"
```

---

### Task 2: 后端事件流按时间顺序排序（TDD）

**Files:**
- Modify: `backend/tests/test_pipeline_aggregator.py`
- Modify: `backend/app/services/pipeline_aggregator.py`

**Step 1: Write the failing test**

```python
from datetime import datetime


def test_pretrade_trace_sorted_by_time():
    session = _make_session()
    run = PreTradeRun(project_id=1, status="success", started_at=datetime(2024, 1, 1, 10, 0, 0))
    session.add(run)
    session.commit()

    snapshot = DecisionSnapshot(project_id=1, status="success", started_at=datetime(2024, 1, 1, 12, 0, 0))
    session.add(snapshot)
    session.commit()

    trade_run = TradeRun(
        project_id=1,
        decision_snapshot_id=snapshot.id,
        status="queued",
        mode="paper",
        started_at=datetime(2024, 1, 1, 9, 0, 0),
    )
    session.add(trade_run)
    session.commit()

    step = PreTradeStep(
        run_id=run.id,
        step_key="decision_snapshot",
        step_order=1,
        status="success",
        started_at=datetime(2024, 1, 1, 11, 0, 0),
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
        created_at=datetime(2024, 1, 1, 9, 30, 0),
    )
    session.add(order)
    session.commit()

    detail = build_pipeline_trace(session, trace_id=f"pretrade:{run.id}")
    assert [event["event_id"] for event in detail["events"]] == [
        f"trade_run:{trade_run.id}",
        f"trade_order:{order.id}",
        f"pretrade_run:{run.id}",
        f"pretrade_step:{step.id}",
        f"decision_snapshot:{snapshot.id}",
    ]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_aggregator.py::test_pretrade_trace_sorted_by_time -v`
Expected: FAIL (order mismatch)

**Step 3: Write minimal implementation**

```python
# backend/app/services/pipeline_aggregator.py
from datetime import datetime


def _event_sort_key(event: dict[str, Any]) -> tuple[datetime, str]:
    when = event.get("started_at") or event.get("ended_at")
    if when is None:
        when = datetime.min
    return when, event.get("event_id", "")

# before return
events.sort(key=_event_sort_key)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_aggregator.py::test_pretrade_trace_sorted_by_time -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/tests/test_pipeline_aggregator.py backend/app/services/pipeline_aggregator.py
git commit -m "fix: sort pipeline trace events by time"
```

---

### Task 3: 前端修复 trace_id 解析并补测试（TDD）

**Files:**
- Create: `frontend/src/utils/pipelineTrace.ts`
- Create: `frontend/src/utils/pipelineTrace.test.ts`
- Modify: `frontend/src/pages/LiveTradePage.tsx`

**Step 1: Write the failing test**

```ts
// frontend/src/utils/pipelineTrace.test.ts
import { describe, expect, it } from "vitest";
import { parsePretradeRunId } from "./pipelineTrace";

describe("parsePretradeRunId", () => {
  it("parses valid pretrade trace id", () => {
    expect(parsePretradeRunId("pretrade:123")).toBe(123);
  });

  it("returns null for invalid input", () => {
    expect(parsePretradeRunId("trade:1")).toBeNull();
    expect(parsePretradeRunId("pretrade:"))
      .toBeNull();
    expect(parsePretradeRunId("pretrade:abc"))
      .toBeNull();
    expect(parsePretradeRunId(null)).toBeNull();
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- pipelineTrace.test.ts`
Expected: FAIL (module not found)

**Step 3: Write minimal implementation**

```ts
// frontend/src/utils/pipelineTrace.ts
export const parsePretradeRunId = (traceId?: string | null): number | null => {
  if (!traceId || !traceId.startsWith("pretrade:")) {
    return null;
  }
  const parts = traceId.split(":");
  if (parts.length < 2 || !parts[1]) {
    return null;
  }
  const parsed = Number(parts[1]);
  return Number.isFinite(parsed) ? parsed : null;
};
```

**Step 4: Update usage**

```ts
// frontend/src/pages/LiveTradePage.tsx
import { parsePretradeRunId } from "../utils/pipelineTrace";

const pipelinePretradeRunId = useMemo(() => {
  return parsePretradeRunId(pipelineTraceId);
}, [pipelineTraceId]);
```

**Step 5: Run test to verify it passes**

Run: `cd frontend && npm run test -- pipelineTrace.test.ts`
Expected: PASS

**Step 6: Commit**

```bash
git add frontend/src/utils/pipelineTrace.ts frontend/src/utils/pipelineTrace.test.ts frontend/src/pages/LiveTradePage.tsx
git commit -m "fix: parse pretrade trace id for pipeline actions"
```

---

### Task 4: 统一回归验证

**Step 1: Backend tests**

Run: `pytest tests/test_pipeline_aggregator.py -v`
Expected: PASS

**Step 2: Frontend tests**

Run: `cd frontend && npm run test -- pipelineTrace.test.ts LiveTradePage.test.ts`
Expected: PASS

**Step 3: Frontend build & restart (mandatory)**

Run: `cd frontend && npm run build`
Run: `systemctl --user restart stocklean-frontend`
Expected: build success, service restarted

**Step 4: Commit any remaining changes**

```bash
git status -sb
```
