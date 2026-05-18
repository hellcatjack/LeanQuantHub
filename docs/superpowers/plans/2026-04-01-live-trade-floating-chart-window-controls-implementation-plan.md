# Live Trade Floating Chart Window Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add drag, edge snapping, size memory, minimize/restore, and persisted desktop floating behavior to the live-trade position chart window.

**Architecture:** Keep floating layout orchestration in `LiveTradePage.tsx` with pure helpers for snap and persisted state normalization. Let `PositionChartWorkspace.tsx` expose controls and resize handle while CSS manages floating, minimized, and dragging states.

**Tech Stack:** React, TypeScript, Vite, Vitest, Playwright, CSS, browser localStorage.

---

### Task 1: Add failing unit and E2E tests
- [ ] Extend `frontend/src/pages/LiveTradePage.test.ts` with failing tests for snap resolution, persisted state normalization, and minimized fallback.
- [ ] Extend `frontend/tests/live-trade-position-chart.spec.ts` with failing desktop tests for drag memory, minimize/restore, and resize.
- [ ] Run the targeted tests and confirm they fail for the expected missing behaviors.

### Task 2: Implement floating window state and persistence
- [ ] Add persisted floating window state, snap helpers, and desktop layout resolution to `frontend/src/pages/LiveTradePage.tsx`.
- [ ] Recompute layout from persisted state on mount and after user interactions.
- [ ] Keep automatic row-avoidance as the fallback path when no user override exists.

### Task 3: Implement controls and styling
- [ ] Update `frontend/src/components/trade/PositionChartWorkspace.tsx` to render drag handle, minimize button, restore button, and resize handle.
- [ ] Update `frontend/src/styles.css` for minimized, dragging, resizable, and snapped floating states.
- [ ] Ensure narrow viewports stay stacked with controls disabled.

### Task 4: Verify and ship
- [ ] Run Vitest, Playwright, `npm run build`, and restart `stocklean-frontend`.
- [ ] Re-run the Playwright spec against the restarted service.
