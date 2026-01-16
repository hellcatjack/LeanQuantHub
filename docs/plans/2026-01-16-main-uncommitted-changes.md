# Main Branch Pending Changes Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Consolidate all current main-branch pending changes (backend/frontend/sql/docs) into one validated commit.

**Architecture:** This is integration work. We will review existing modifications for consistency, ensure new routes/services/migrations are wired correctly, run the frontend build to validate UI changes, then stage and commit everything in a single changeset.

**Tech Stack:** FastAPI, React + Vite, MySQL (SQL patches), Git.

### Task 1: Inventory and sanity-check the pending changes

**Files:**
- Review: `backend/.env.example`
- Review: `backend/app/main.py`
- Review: `backend/app/models.py`
- Review: `backend/app/schemas.py`
- Review: `backend/app/routes/ib.py`
- Review: `backend/app/routes/trade.py`
- Review: `backend/app/services/ib_history_runner.py`
- Review: `backend/app/services/ib_market.py`
- Review: `backend/app/services/ib_settings.py`
- Review: `backend/app/services/trade_executor.py`
- Review: `backend/app/services/trade_orders.py`
- Review: `backend/requirements.txt`
- Review: `frontend/src/App.tsx`
- Review: `frontend/src/components/Sidebar.tsx`
- Review: `frontend/src/pages/DataPage.tsx`
- Review: `frontend/src/pages/ProjectsPage.tsx`
- Review: `frontend/src/pages/LiveTradePage.tsx`
- Review: `frontend/src/i18n.tsx`
- Review: `frontend/src/styles.css`
- Review: `docs/todolists/IBAutoTradeTODO.md`
- Review: `docs/todolists/MenuNavigationTODO.md`
- Review: `deploy/mysql/patches/20260115_add_ib_contract_cache.sql`
- Review: `deploy/mysql/patches/20260115_add_ib_history_jobs.sql`
- Review: `deploy/mysql/patches/20260115_add_ib_settings.sql`
- Review: `deploy/mysql/patches/20260115_add_trade_orders.sql`
- Review: `deploy/mysql/patches/20260116_add_ib_api_mode.sql`
- Review: `deploy/mysql/patches/20260116_add_ib_regulatory_snapshot.sql`

**Step 1: List the modified/untracked files**

Run: `git status -sb`
Expected: All pending changes listed (no surprises, no secrets).

**Step 2: Inspect the scope of changes**

Run: `git diff --stat`
Expected: Matches the known backend/frontend/sql/docs changes.

**Step 3: Inspect the critical diffs**

Run: `git diff`
Expected: No secrets; routes/services wired; SQL patches contain required headers.

### Task 2: Validate UI build (existing tests only)

**Step 1: Frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds without errors.

**Step 2: Backend tests (if present)**

Run: `python -m pytest -q`
Expected: If tests exist, they pass; if none, no tests collected.

### Task 3: Stage and commit as a single changeset

**Step 1: Stage all changes**

Run: `git add backend frontend deploy/mysql docs`
Expected: All modified and new files staged.

**Step 2: Commit**

Run: `git commit -m "feat: integrate ib trading scaffolding and menu updates"`
Expected: Single commit with all pending changes.

**Step 3: Confirm clean working tree**

Run: `git status -sb`
Expected: Clean working tree.
