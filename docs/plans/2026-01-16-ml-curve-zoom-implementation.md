# ML 训练曲线可读性优化 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve ML training curve readability by adding a scaled validation axis, reducing font sizes, and introducing unit tests via Vitest.

**Architecture:** Keep the existing SVG chart and extract scale/format helpers into a small utility module with unit tests. Update ProjectsPage to render dual axes and use the new helpers.

**Tech Stack:** React + Vite, Vitest, TypeScript, SVG.

### Task 1: Add frontend test tooling and create a failing test

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/utils/mlCurve.ts`
- Test: `frontend/src/utils/mlCurve.test.ts`

**Step 1: Add Vitest script/dependency**

Edit `frontend/package.json`:
- Add `"test": "vitest run"` to scripts
- Add `"vitest": "^2.x"` to devDependencies

**Step 2: Add Vitest config**

Edit `frontend/vite.config.ts`:
- Add `test: { environment: "node" }`

**Step 3: Write a failing test**

Create `frontend/src/utils/mlCurve.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { computePaddedRange, formatAxisValue } from "./mlCurve";

describe("computePaddedRange", () => {
  it("adds padding when values are flat", () => {
    const res = computePaddedRange([0.123, 0.123]);
    expect(res).not.toBeNull();
    expect(res!.max).toBeGreaterThan(res!.min);
  });
});

describe("formatAxisValue", () => {
  it("adds more precision for small spans", () => {
    expect(formatAxisValue(0.123456, 0.005)).toBe("0.12346");
  });
});
```

**Step 4: Run the test to verify it fails**

Run: `cd frontend && npm test`  
Expected: FAIL (module not found or missing function).

### Task 2: Implement minimal helper functions to pass tests

**Files:**
- Create: `frontend/src/utils/mlCurve.ts`

**Step 1: Implement minimal helpers**

```ts
export type AxisRange = {
  min: number;
  max: number;
  span: number;
  rawMin: number;
  rawMax: number;
};

export const computePaddedRange = (
  values: number[],
  options: { minSpanRatio?: number; padRatio?: number } = {}
): AxisRange | null => {
  const finite = values.filter((v) => Number.isFinite(v));
  if (!finite.length) {
    return null;
  }
  const rawMin = Math.min(...finite);
  const rawMax = Math.max(...finite);
  const rawSpan = rawMax - rawMin;
  const base = Math.max(Math.abs(rawMin), Math.abs(rawMax), 1);
  const minSpan = base * (options.minSpanRatio ?? 0.02);
  const span = Math.max(rawSpan, minSpan);
  const pad = span * (options.padRatio ?? 0.1);
  return {
    rawMin,
    rawMax,
    min: rawMin - pad,
    max: rawMax + pad,
    span: span + pad * 2,
  };
};

export const formatAxisValue = (value: number, span: number): string => {
  if (!Number.isFinite(value)) {
    return "-";
  }
  const absSpan = Math.abs(span);
  if (absSpan < 0.01) {
    return value.toFixed(5);
  }
  if (absSpan < 0.1) {
    return value.toFixed(4);
  }
  if (absSpan < 1) {
    return value.toFixed(3);
  }
  return value.toFixed(2);
};
```

**Step 2: Run tests to verify they pass**

Run: `cd frontend && npm test`  
Expected: PASS.

### Task 3: Update ML curve rendering to use dual axis + scaled valid

**Files:**
- Modify: `frontend/src/pages/ProjectsPage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Modify: `frontend/src/styles.css`

**Step 1: Use helpers in render**

In `renderMlCurve`:
- Compute `globalMin/globalMax` from train+valid (existing behavior).
- Compute `validRange = computePaddedRange(valid)`; use it for valid path and right-axis ticks.
- Use `formatAxisValue` for both left/right axis labels.
- Best point uses valid range mapping.

**Step 2: Update legend text**

Add i18n key `projects.ml.metricCurveValidScaled`:
- zh: `验证（放大）`
- en: `Valid (scaled)`

**Step 3: Update styles**

Update `.ml-curve-axis-label` to 10px, add `.ml-curve-axis-label.valid` color.
Update `.ml-curve-line.valid` to dashed + thinner.
Update `.ml-curve-best-label` to smaller font.
Update legend font-size to 11px.

**Step 4: Commit**

```bash
git add frontend/src/utils/mlCurve.ts frontend/src/utils/mlCurve.test.ts frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/src/pages/ProjectsPage.tsx frontend/src/i18n.tsx frontend/src/styles.css
git commit -m "feat: improve ml curve readability"
```

### Task 4: Verify build and UI

**Step 1: Frontend build**

Run: `cd frontend && npm run build`  
Expected: Build succeeds.

**Step 2: Playwright smoke**

Run: `npx playwright test`  
Expected: If no tests exist, report and skip.
