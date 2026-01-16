# Frontend/Backend Build Location Enforcement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure all build/release instructions explicitly run inside `frontend/` and `backend/`, avoiding root-level `npm` usage.

**Architecture:** Documentation-only alignment. Update run/build instructions in AGENTS/README and relevant TODO/plan docs so operators always execute commands in the correct subdirectories.

**Tech Stack:** Markdown docs, project run scripts.

### Task 1: Update run/build guidance in project docs

**Files:**
- Modify: `AGENTS.md:32-40`
- Modify: `README.md:38-52`
- Modify: `docs/todolists/MenuNavigationTODO.md:11-40`
- Modify: `docs/plans/2026-01-16-main-uncommitted-changes.md:54-68`

**Step 1: Edit AGENTS build commands**

Update “前端”/“后端” run instructions to include `cd frontend` and `cd backend`.

**Step 2: Edit README deployment section**

Ensure build commands explicitly run in `frontend/` (already present; reinforce with wording if needed).

**Step 3: Edit TODO/plan docs**

Replace `npm run build` with `cd frontend && npm run build` in the two docs.

**Step 4: Commit**

```bash
git add AGENTS.md README.md docs/todolists/MenuNavigationTODO.md docs/plans/2026-01-16-main-uncommitted-changes.md
git commit -m "docs: clarify frontend/backend build locations"
```

### Task 2: Verify build and publish steps

**Step 1: Frontend build**

Run: `cd frontend && npm run build`  
Expected: Build succeeds (vite output).

**Step 2: Restart frontend service**

Run: `systemctl --user restart stocklean-frontend`  
Expected: Service restarts without error.

