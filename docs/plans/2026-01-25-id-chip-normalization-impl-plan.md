# ID Chip Normalization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Introduce a reusable ID Chip with copy support and standardize ID display across LiveTrade, Data, Projects, Backtests/Reports.

**Architecture:** Add a small reusable UI component (`IdChip`) and progressively replace raw ID text with chips in key pages. Keep backend untouched; UI consumes existing IDs.

**Tech Stack:** React + Vite (frontend), Playwright, Jest/React Testing Library (if available), existing CSS.

---

### Task 1: Create IdChip component + unit tests

**Files:**
- Create: `frontend/src/components/IdChip.tsx`
- Create: `frontend/src/components/IdChip.test.tsx`
- Modify: `frontend/src/styles.css`

**Step 1: Write failing unit test**

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import IdChip from "./IdChip";

test("renders label + value and copies numeric id", async () => {
  const writeText = vi.fn();
  Object.assign(navigator, { clipboard: { writeText } });

  render(<IdChip label="Run" value={123} />);
  expect(screen.getByText("Run#123")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /复制|Copy/i }));
  expect(writeText).toHaveBeenCalledWith("123");
});
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd frontend && npm test -- --runTestsByPath src/components/IdChip.test.tsx
```
Expected: FAIL (component missing).

**Step 3: Implement IdChip**

```tsx
import { useState } from "react";

interface IdChipProps {
  label: string;
  value: number | string | null | undefined;
}

export default function IdChip({ label, value }: IdChipProps) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const text = `${label}#${value}`;
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(String(value));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      // ignore
    }
  };
  return (
    <span className="id-chip" title={text}>
      <span className="id-chip-text">{text}</span>
      <button className="id-chip-copy" onClick={copy} aria-label="Copy ID">
        {copied ? "✓" : "⧉"}
      </button>
    </span>
  );
}
```

**Step 4: Add CSS**

```css
.id-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: #f8faff;
  font-size: 12px;
}
.id-chip-copy {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
}
```

**Step 5: Run test to verify it passes**

Run:
```bash
cd frontend && npm test -- --runTestsByPath src/components/IdChip.test.tsx
```
Expected: PASS.

**Step 6: Commit**

```bash
git add frontend/src/components/IdChip.tsx frontend/src/components/IdChip.test.tsx frontend/src/styles.css
git commit -m "feat: add id chip component" 
```

---

### Task 2: LiveTrade ID Chips

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Test: `frontend/tests/live-trade.spec.ts`

**Step 1: Write failing Playwright test**

Add test:
```ts
test("live trade shows id chips in execution context", async ({ page }) => {
  await page.route("**/api/projects/page**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [{ id: 16, name: "Project 16" }], total: 1, page: 1, page_size: 200 }) })
  );
  await page.route("**/api/decisions/latest?project_id=16", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: 91, project_id: 16, snapshot_date: "2026-01-25" }) })
  );
  await page.route("**/api/trade/runs**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([{ id: 88, project_id: 16, decision_snapshot_id: 91, mode: "paper", status: "queued", created_at: "2026-01-25T00:00:00Z" }]) })
  );
  await page.goto("/live-trade");
  await expect(page.getByText(/Project#16/i)).toBeVisible();
  await expect(page.getByText(/Snapshot#91/i)).toBeVisible();
  await expect(page.getByText(/Run#88/i)).toBeVisible();
});
```

**Step 2: Run test to verify it fails**

```bash
cd frontend && npx playwright test tests/live-trade.spec.ts -g "id chips"
```
Expected: FAIL (chips not present).

**Step 3: Implement chips**

- Import `IdChip` and use in execution context and run table columns.
- Replace raw `#id` text with `IdChip` components.

**Step 4: Run test to verify it passes**

```bash
cd frontend && npx playwright test tests/live-trade.spec.ts -g "id chips"
```
Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/tests/live-trade.spec.ts
 git commit -m "feat: show id chips in live trade" 
```

---

### Task 3: DataPage ID Chips

**Files:**
- Modify: `frontend/src/pages/DataPage.tsx`
- Test: `frontend/tests/data-page.spec.ts` (create if not exists)

**Step 1: Write failing Playwright test**

```ts
test("data page shows id chips for pretrade runs", async ({ page }) => {
  await page.goto("/data");
  await expect(page.getByText(/Run#/i)).toBeVisible();
});
```

**Step 2: Run test to verify it fails**

```bash
cd frontend && npx playwright test tests/data-page.spec.ts -g "id chips"
```
Expected: FAIL.

**Step 3: Implement chips**

- Use `IdChip` in Pretrade run summary and history tables (run id, job id, step id).

**Step 4: Run test to verify it passes**

```bash
cd frontend && npx playwright test tests/data-page.spec.ts -g "id chips"
```
Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/src/pages/DataPage.tsx frontend/tests/data-page.spec.ts
 git commit -m "feat: add id chips to data page" 
```

---

### Task 4: Projects / Backtests / Reports ID Chips

**Files:**
- Modify: `frontend/src/pages/ProjectsPage.tsx`
- Modify: `frontend/src/pages/BacktestsPage.tsx`
- Modify: `frontend/src/components/ReportsPanel.tsx`
- Test: `frontend/tests/projects-page.spec.ts` (if needed)

**Step 1: Write failing Playwright test**

```ts
test("projects page shows id chips for snapshots", async ({ page }) => {
  await page.goto("/projects");
  await expect(page.getByText(/Snapshot#/i)).toBeVisible();
});
```

**Step 2: Run test to verify it fails**

```bash
cd frontend && npx playwright test tests/projects-page.spec.ts -g "id chips"
```
Expected: FAIL.

**Step 3: Implement chips**

- ProjectsPage: decision snapshot id display
- BacktestsPage/ReportsPanel: run ids displayed with chips

**Step 4: Run test to verify it passes**

```bash
cd frontend && npx playwright test tests/projects-page.spec.ts -g "id chips"
```
Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/src/pages/ProjectsPage.tsx frontend/src/pages/BacktestsPage.tsx frontend/src/components/ReportsPanel.tsx frontend/tests/projects-page.spec.ts
 git commit -m "feat: add id chips to project/backtest/report" 
```

---

### Task 5: Final verification/build

**Step 1: Run smoke suite**
```bash
cd frontend && npx playwright test tests/live-trade.spec.ts -g "live trade"
```
Expected: PASS.

**Step 2: Build & restart**
```bash
cd frontend && npm run build
systemctl --user restart stocklean-frontend
```
Expected: build success.

**Step 3: Commit any remaining changes**
```bash
git status -sb
```
Commit if needed.
