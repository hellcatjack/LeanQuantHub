# Live Trade Floating Chart Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make live-trade positions rows single-line on desktop and move the professional chart into an adaptive floating card that avoids the selected row.

**Architecture:** Keep the positions table as the primary full-width surface. Compute floating chart placement in `LiveTradePage.tsx` using DOM refs and a pure layout helper. Let `PositionChartWorkspace` accept floating classes while CSS handles desktop floating and narrow-screen fallback.

**Tech Stack:** React, TypeScript, Vite, Vitest, Playwright, CSS.

---

### Task 1: Add failing tests for floating layout and compact rows
- [ ] Add Vitest cases for `resolvePositionChartFloatingLayout()` in `frontend/src/pages/LiveTradePage.test.ts`
- [ ] Add Playwright checks for desktop floating chart geometry and single-line toolbar in `frontend/tests/live-trade-position-chart.spec.ts`
- [ ] Run targeted tests and confirm failures

### Task 2: Implement floating layout calculation and row refs
- [ ] Add layout helper and floating state management in `frontend/src/pages/LiveTradePage.tsx`
- [ ] Track selected row DOM position and pass floating props into `PositionChartWorkspace`
- [ ] Convert action cell markup to a single-line toolbar with stable test ids

### Task 3: Implement floating chart styling and responsive fallback
- [ ] Update `frontend/src/components/trade/PositionChartWorkspace.tsx` to accept floating props/classes
- [ ] Update `frontend/src/styles.css` for full-width table, single-line action toolbar, floating chart desktop mode, and stacked narrow mode
- [ ] Run Vitest, Playwright, build, and restart `stocklean-frontend`
