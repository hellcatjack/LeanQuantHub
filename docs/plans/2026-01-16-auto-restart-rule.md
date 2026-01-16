# Frontend Auto-Restart Rule Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Document that frontend changes must trigger an automatic `npm run build` and `stocklean-frontend` restart without asking for confirmation.

**Architecture:** Documentation-only update in AGENTS.md to clarify the mandatory auto-restart rule and reinforce that commands run inside `frontend/`.

**Tech Stack:** Markdown docs.

### Task 1: Update AGENTS.md with auto-restart rule

**Files:**
- Modify: `AGENTS.md:32-40`

**Step 1: Edit AGENTS.md**

Add a bullet stating: “前端代码变更后自动执行 `cd frontend && npm run build` 并重启 `stocklean-frontend`，无需询问。”

**Step 2: No tests required (documentation-only)**

**Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs: require auto frontend restart after changes"
```
