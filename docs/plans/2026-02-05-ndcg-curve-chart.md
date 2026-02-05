# NDCG Curve Chart Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在训练曲线图中以多曲线形式展示 NDCG@10 / NDCG@50 / NDCG@100（验证集），并使用 lightweight-charts 提升表现力。

**Architecture:** 后端训练在 LGBM ranker 训练结果中新增 `curve_ndcg`（多曲线 payload），前端读取该字段并用 lightweight-charts 绘制 3 条验证曲线，缺失时回退到旧单曲线。禁用 git worktree，直接在主工作区执行。

**Tech Stack:** FastAPI, Python, React, Vite, lightweight-charts, Vitest, Pytest

---

### Task 1: 新增 NDCG 多曲线解析单元测试

**Files:**
- Create: `ml/tests/test_ndcg_curve_payload.py`

**Step 1: Write the failing test**
```python
from ml import train_torch


def test_extract_lgbm_ndcg_curves_from_evals():
    evals = {
        "valid_0": {
            "ndcg@10": [0.1, 0.2, 0.25],
            "ndcg@50": [0.3, 0.31, 0.33],
            "ndcg@100": [0.4, 0.41, 0.42],
        }
    }
    payload = train_torch._build_ndcg_curve_payload(evals)
    assert payload is not None
    assert payload["iterations"] == [1, 2, 3]
    assert payload["valid"]["ndcg@10"] == [0.1, 0.2, 0.25]
    assert payload["valid"]["ndcg@50"] == [0.3, 0.31, 0.33]
    assert payload["valid"]["ndcg@100"] == [0.4, 0.41, 0.42]
```

**Step 2: Run test to verify it fails**
Run: `python -m pytest ml/tests/test_ndcg_curve_payload.py -q`
Expected: FAIL (function missing)

**Step 3: Write minimal implementation**
- Modify `ml/train_torch.py`:
  - Add `_extract_lgbm_ndcg_curves(evals_result)` helper to collect valid series for ndcg@10/50/100
  - Add `_build_ndcg_curve_payload(evals_result)` to normalize lengths + generate iterations

**Step 4: Run test to verify it passes**
Run: `python -m pytest ml/tests/test_ndcg_curve_payload.py -q`
Expected: PASS

**Step 5: Commit**
```bash
git add ml/train_torch.py ml/tests/test_ndcg_curve_payload.py
git commit -m "feat: add ndcg curve payload helper"
```

---

### Task 2: 训练输出写入 curve_ndcg

**Files:**
- Modify: `ml/train_torch.py`

**Step 1: Write the failing test**
```python
from ml import train_torch


def test_curve_ndcg_payload_keeps_min_length():
    evals = {
        "valid": {
            "ndcg@10": [0.1, 0.2, 0.3],
            "ndcg@50": [0.2, 0.3],
            "ndcg@100": [0.3, 0.4, 0.5, 0.6],
        }
    }
    payload = train_torch._build_ndcg_curve_payload(evals)
    assert payload["iterations"] == [1, 2]
    assert len(payload["valid"]["ndcg@10"]) == 2
```

**Step 2: Run test to verify it fails**
Run: `python -m pytest ml/tests/test_ndcg_curve_payload.py -q`
Expected: FAIL (length handling not implemented)

**Step 3: Implement**
- `ml/train_torch.py`:
  - 在 LGBM 单窗口训练完成时：在 `metrics` 中写入 `curve_ndcg`
  - 在 walk-forward 汇总时：对每个窗口提取 ndcg 曲线并按指标聚合平均，写入 `metrics_payload.curve_ndcg`

**Step 4: Run test to verify it passes**
Run: `python -m pytest ml/tests/test_ndcg_curve_payload.py -q`
Expected: PASS

**Step 5: Commit**
```bash
git add ml/train_torch.py ml/tests/test_ndcg_curve_payload.py
git commit -m "feat: emit ndcg multi-curve payload"
```

---

### Task 3: 前端提取 NDCG 曲线数据（TDD）

**Files:**
- Modify: `frontend/src/utils/mlCurve.ts`
- Modify: `frontend/src/utils/mlCurve.test.ts`

**Step 1: Write the failing test**
```ts
import { extractNdcgCurves } from "./mlCurve";

describe("extractNdcgCurves", () => {
  it("reads curve_ndcg.valid for ndcg series", () => {
    const metrics = {
      curve_ndcg: {
        iterations: [1, 2, 3],
        valid: {
          "ndcg@10": [0.1, 0.2, 0.3],
          "ndcg@50": [0.2, 0.3, 0.4],
          "ndcg@100": [0.3, 0.4, 0.5],
        },
      },
    };
    const result = extractNdcgCurves(metrics);
    expect(result?.iterations).toEqual([1, 2, 3]);
    expect(result?.series[0].key).toBe("ndcg@10");
    expect(result?.series[0].values).toEqual([0.1, 0.2, 0.3]);
  });
});
```

**Step 2: Run test to verify it fails**
Run: `cd frontend && npx vitest run src/utils/mlCurve.test.ts`
Expected: FAIL (function missing)

**Step 3: Implement minimal helper**
- `frontend/src/utils/mlCurve.ts`:
  - add `extractNdcgCurves(metrics)` that reads `metrics.curve_ndcg` / `metrics.walk_forward.curve_ndcg` / `metrics.walkForward.curve_ndcg`
  - returns `{ iterations, series: [{ key, values }] }` in fixed key order

**Step 4: Run test to verify it passes**
Run: `cd frontend && npx vitest run src/utils/mlCurve.test.ts`
Expected: PASS

**Step 5: Commit**
```bash
git add frontend/src/utils/mlCurve.ts frontend/src/utils/mlCurve.test.ts
git commit -m "feat: extract ndcg curves for training chart"
```

---

### Task 4: 新训练曲线组件（lightweight-charts）

**Files:**
- Create: `frontend/src/components/MlTrainingCurveChart.tsx`
- Modify: `frontend/src/styles.css`

**Step 1: Write the failing test**
```ts
import { renderToString } from "react-dom/server";
import MlTrainingCurveChart from "./MlTrainingCurveChart";

test("renders training curve chart wrapper", () => {
  const html = renderToString(
    <MlTrainingCurveChart
      iterations={[1, 2]}
      series={[{ key: "ndcg@10", label: "NDCG@10", values: [0.1, 0.2] }]}
    />
  );
  expect(html).toContain("ml-training-curve");
});
```

**Step 2: Run test to verify it fails**
Run: `cd frontend && npx vitest run src/components/MlTrainingCurveChart.test.tsx`
Expected: FAIL (component missing)

**Step 3: Implement minimal component**
- 组件内部用 `createChart` 创建三条 line series
- 支持 legend（最新值 + hover 时更新）
- 颜色固定：@10 蓝、@50 绿、@100 橙

**Step 4: Run test to verify it passes**
Run: `cd frontend && npx vitest run src/components/MlTrainingCurveChart.test.tsx`
Expected: PASS

**Step 5: Commit**
```bash
git add frontend/src/components/MlTrainingCurveChart.tsx frontend/src/components/MlTrainingCurveChart.test.tsx frontend/src/styles.css
git commit -m "feat: add lightweight training curve chart"
```

---

### Task 5: 集成到 ProjectsPage

**Files:**
- Modify: `frontend/src/pages/ProjectsPage.tsx`

**Step 1: Write the failing test**
```ts
import { extractNdcgCurves } from "../utils/mlCurve";

test("prefers curve_ndcg when present", () => {
  const metrics = { curve_ndcg: { iterations: [1], valid: { "ndcg@10": [0.1] } } };
  const extracted = extractNdcgCurves(metrics);
  expect(extracted?.iterations).toEqual([1]);
});
```

**Step 2: Run test to verify it fails**
Run: `cd frontend && npx vitest run src/utils/mlCurve.test.ts`
Expected: FAIL (behavior missing)

**Step 3: Implement**
- 在 ProjectsPage 中改用 `MlTrainingCurveChart` + `extractNdcgCurves`
- 若没有 ndcg 曲线，回退旧 `mlCurve` 单线数据

**Step 4: Run test to verify it passes**
Run: `cd frontend && npx vitest run src/utils/mlCurve.test.ts`
Expected: PASS

**Step 5: Commit**
```bash
git add frontend/src/pages/ProjectsPage.tsx
git commit -m "feat: render ndcg curves in training chart"
```

---

### Task 6: 构建与验证

**Step 1: Build frontend**
Run: `cd frontend && npm run build`
Expected: build success

**Step 2: Restart services**
Run: `systemctl --user restart stocklean-backend stocklean-frontend`
Expected: no errors

---

## Verification Checklist
- 新增测试先失败再通过
- `curve_ndcg` 出现在 LGBM 训练输出 metrics 中
- 前端训练曲线展示 NDCG@10/50/100 三条线

---

## Notes
- 禁止使用 git worktree，计划在主工作区执行。
