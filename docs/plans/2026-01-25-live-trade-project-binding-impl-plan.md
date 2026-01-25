# Live Trade Project Binding Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an explicit project binding section on the live trade page, show latest decision snapshot status, and gate execution based on snapshot readiness.

**Architecture:** Frontend-only change: LiveTradePage loads project list and latest decision snapshot via existing APIs (`/api/projects/page`, `/api/decisions/latest`). UI shows binding summary and disables execution when snapshot missing. No backend changes required.

**Tech Stack:** React + Vite (frontend), Playwright tests, existing FastAPI endpoints.

---

### Task 1: Add failing Playwright tests for project binding

**Files:**
- Modify: `frontend/tests/live-trade.spec.ts`

**Step 1: Write the failing tests**

Add three tests at the end of the file (use unique test names). Keep mocks minimal and reuse existing routes when possible.

```ts
import { test, expect } from "@playwright/test";

// ... existing tests ...

test("live trade requires project binding before execute", async ({ page }) => {
  await page.route("**/api/projects/page**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0, page: 1, page_size: 200 }),
    })
  );
  await page.route("**/api/decisions/latest**", (route) => route.abort());
  await page.route("**/api/trade/runs**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) })
  );
  await page.goto("/live-trade");
  await expect(
    page.locator(".form-hint", { hasText: /请选择项目|Select a project/i })
  ).toBeVisible();
  await expect(
    page.locator("button", { hasText: /执行交易|Execute/i })
  ).toBeDisabled();
});

test("live trade disables execute when snapshot missing", async ({ page }) => {
  await page.route("**/api/projects/page**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{ id: 16, name: "Project 16" }],
        total: 1,
        page: 1,
        page_size: 200,
      }),
    })
  );
  await page.route("**/api/decisions/latest**", (route) =>
    route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "snapshot not found" }) })
  );
  await page.route("**/api/trade/runs**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) })
  );
  await page.goto("/live-trade");
  await expect(
    page.locator(".form-hint", { hasText: /未生成快照|Snapshot not generated/i })
  ).toBeVisible();
  await expect(
    page.locator("button", { hasText: /执行交易|Execute/i })
  ).toBeDisabled();
});

test("live trade enables execute when snapshot present", async ({ page }) => {
  await page.route("**/api/projects/page**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{ id: 16, name: "Project 16" }],
        total: 1,
        page: 1,
        page_size: 200,
      }),
    })
  );
  await page.route("**/api/decisions/latest?project_id=16", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 91,
        project_id: 16,
        status: "success",
        snapshot_date: "2026-01-25",
        summary: { total_items: 42, version: "v1" },
      }),
    })
  );
  await page.route("**/api/trade/runs**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) })
  );
  await page.goto("/live-trade");
  await expect(page.locator(".meta-row", { hasText: /快照日期|Snapshot date/i })).toBeVisible();
  await expect(
    page.locator("button", { hasText: /执行交易|Execute/i })
  ).not.toBeDisabled();
});
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd frontend && npx playwright test tests/live-trade.spec.ts -g "project binding"
```
Expected: FAIL because UI elements/texts do not exist yet.

---

### Task 2: Implement project binding UI and snapshot loading

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`

**Step 1: Add minimal state + loaders (implementation)**

Add types/state near other interfaces:
```ts
interface ProjectSummary {
  id: number;
  name: string;
  description?: string | null;
}

interface DecisionSnapshotSummary {
  id: number;
  project_id: number;
  status?: string | null;
  snapshot_date?: string | null;
  summary?: Record<string, any> | null;
}
```

Add state + loaders:
```ts
const [projects, setProjects] = useState<ProjectSummary[]>([]);
const [projectError, setProjectError] = useState("");
const [selectedProjectId, setSelectedProjectId] = useState("");
const [snapshot, setSnapshot] = useState<DecisionSnapshotSummary | null>(null);
const [snapshotError, setSnapshotError] = useState("");
const [snapshotLoading, setSnapshotLoading] = useState(false);

const loadProjects = async () => {
  try {
    const res = await api.get("/api/projects/page", { params: { page: 1, page_size: 200 } });
    const items = res.data.items || [];
    setProjects(items);
    setProjectError("");
    setSelectedProjectId((prev) => (prev && items.some((p: any) => String(p.id) === prev) ? prev : (items[0] ? String(items[0].id) : "")));
  } catch {
    setProjects([]);
    setProjectError(t("trade.projectLoadError"));
  }
};

const loadLatestSnapshot = async (projectId: string) => {
  if (!projectId) {
    setSnapshot(null);
    setSnapshotError("");
    return;
  }
  setSnapshotLoading(true);
  setSnapshotError("");
  try {
    const res = await api.get(`/api/decisions/latest`, { params: { project_id: Number(projectId) } });
    setSnapshot(res.data);
  } catch (err: any) {
    if (err?.response?.status === 404) {
      setSnapshot(null);
      setSnapshotError(t("trade.snapshotMissing"));
    } else {
      setSnapshot(null);
      setSnapshotError(t("trade.snapshotLoadError"));
    }
  } finally {
    setSnapshotLoading(false);
  }
};
```

Wire into lifecycle:
```ts
useEffect(() => {
  loadProjects();
}, []);

useEffect(() => {
  loadLatestSnapshot(selectedProjectId);
}, [selectedProjectId]);
```

Compute gating:
```ts
const snapshotReady = Boolean(snapshot?.id);
const canExecute = snapshotReady && Boolean(selectedProjectId);
```

**Step 2: Render “项目绑定” card in LiveTradePage**

Insert near the top of the page (before trade runs). Example layout:
```tsx
<div className="card">
  <div className="card-title">{t("trade.projectBindingTitle")}</div>
  <div className="card-meta">{t("trade.projectBindingMeta")}</div>
  {projectError && <div className="form-hint">{projectError}</div>}
  <div className="form-grid two-col">
    <div className="form-row">
      <label className="form-label">{t("trade.projectSelect")}</label>
      <select
        className="form-select"
        value={selectedProjectId}
        onChange={(e) => setSelectedProjectId(e.target.value)}
      >
        <option value="">{t("trade.projectSelectPlaceholder")}</option>
        {projects.map((project) => (
          <option key={project.id} value={project.id}>
            #{project.id} · {project.name}
          </option>
        ))}
      </select>
    </div>
  </div>
  {!selectedProjectId && (
    <div className="form-hint">{t("trade.projectSelectHint")}</div>
  )}
  <div className="meta-list">
    <div className="meta-row">
      <span>{t("trade.snapshotStatus")}</span>
      <strong>{snapshotReady ? t("trade.snapshotReady") : t("trade.snapshotMissing")}</strong>
    </div>
    <div className="meta-row">
      <span>{t("trade.snapshotDate")}</span>
      <strong>{snapshot?.snapshot_date || t("common.none")}</strong>
    </div>
    <div className="meta-row">
      <span>{t("trade.snapshotId")}</span>
      <strong>{snapshot?.id ? `#${snapshot.id}` : t("common.none")}</strong>
    </div>
  </div>
  {snapshotError && <div className="form-hint">{snapshotError}</div>}
</div>
```

**Step 3: Gate execution button + show context**

Replace the execute button area so it reflects binding context:
```tsx
<div className="meta-row">
  <span>{t("trade.executeContext")}</span>
  <strong>
    {selectedProjectId
      ? `${t("trade.projectShort")}${selectedProjectId}`
      : t("trade.projectSelectPlaceholder")}
    {snapshot?.snapshot_date ? ` · ${snapshot.snapshot_date}` : ""}
    {snapshot?.id ? ` · #${snapshot.id}` : ""}
  </strong>
</div>
```

Change execute button to:
```tsx
<button className="button-primary" onClick={executeTradeRun} disabled={executeLoading || !canExecute}>
  {executeLoading ? t("common.actions.loading") : t("trade.executeSubmit")}
</button>
```

Show hint when cannot execute:
```tsx
{!canExecute && (
  <div className="form-hint">{selectedProjectId ? t("trade.executeBlockedSnapshot") : t("trade.executeBlockedProject")}</div>
)}
```

**Step 4: Update i18n**

Add required text keys in `frontend/src/i18n.tsx` (zh/en):
- `trade.projectBindingTitle`
- `trade.projectBindingMeta`
- `trade.projectSelect`
- `trade.projectSelectPlaceholder`
- `trade.projectSelectHint`
- `trade.snapshotStatus`
- `trade.snapshotReady`
- `trade.snapshotMissing`
- `trade.snapshotDate`
- `trade.snapshotId`
- `trade.snapshotLoadError`
- `trade.projectLoadError`
- `trade.executeContext`
- `trade.executeBlockedProject`
- `trade.executeBlockedSnapshot`
- `trade.projectShort`

**Step 5: Run test to verify it passes**

Run:
```bash
cd frontend && npx playwright test tests/live-trade.spec.ts -g "project binding"
```
Expected: PASS.

**Step 6: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx frontend/tests/live-trade.spec.ts
git commit -m "feat: add live trade project binding" 
```

---

### Task 3: Final verification and handoff

**Step 1: Run focused UI smoke**

```bash
cd frontend && npx playwright test tests/live-trade.spec.ts -g "live trade" 
```
Expected: PASS.

**Step 2: Build & restart frontend**

```bash
cd frontend && npm run build
systemctl --user restart stocklean-frontend
```
Expected: build succeeds and frontend restarts.

**Step 3: Commit any remaining changes**

```bash
git status -sb
```
If anything remains, commit with a descriptive message.

---

## Notes
- Follow @superpowers:test-driven-development strictly.
- Avoid adding backend endpoints unless UI cannot be fulfilled by `/api/projects/page` and `/api/decisions/latest`.
- Keep UI minimal and consistent with existing card/meta layout.
