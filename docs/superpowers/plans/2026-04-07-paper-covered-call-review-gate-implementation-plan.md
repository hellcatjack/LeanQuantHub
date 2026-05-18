# Paper Covered Call Review Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a paper-only covered call review gate that freezes review snapshots, emits approval tokens, and records audit evidence without submitting real option orders.

**Architecture:** Keep `prepare` as the execution-planning stage and add a separate `review` stage. The review service will call `prepare`, capture runtime/position/open-order summaries, emit a short-lived approval token, write artifacts, and append an audit log entry.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy session, local JSON artifacts, pytest.

---

### Task 1: Review models and schema

**Files:**
- Modify: `backend/app/services/trade_option_models.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_trade_option_models.py`

- [ ] Add failing tests for `CoveredCallReviewRequest` and `CoveredCallReviewResult` defaults.
- [ ] Run: `cd /app/stocklean && pytest backend/tests/test_trade_option_models.py -q`
- [ ] Implement minimal request/result models in service models and API schemas.
- [ ] Re-run the same test command until green.

### Task 2: Review service

**Files:**
- Create: `backend/app/services/covered_call_review.py`
- Test: `backend/tests/test_covered_call_review.py`

- [ ] Add failing tests for:
  - blocked review returns no token
  - ready review generates token and bundle
  - review_required review preserves risk tags and still generates token
  - audit log is recorded
- [ ] Run: `cd /app/stocklean && pytest backend/tests/test_covered_call_review.py -q`
- [ ] Implement minimal review service on top of `prepare_covered_call_execution()`.
- [ ] Re-run the same test command until green.

### Task 3: Route integration

**Files:**
- Modify: `backend/app/routes/trade.py`
- Test: `backend/tests/test_covered_call_review_route.py`

- [ ] Add failing route tests for `paper_only`, `dry_run_only`, and successful passthrough.
- [ ] Run: `cd /app/stocklean && pytest backend/tests/test_covered_call_review_route.py -q`
- [ ] Implement `POST /api/trade/options/covered-call/review`.
- [ ] Re-run the same test command until green.

### Task 4: Full verification

**Files:**
- Verify only existing covered-call files changed in this phase.

- [ ] Run:
  `cd /app/stocklean && pytest backend/tests/test_trade_option_models.py backend/tests/test_ib_options_market.py backend/tests/test_options_eligibility.py backend/tests/test_covered_call_planner.py backend/tests/test_covered_call_pilot_route.py backend/tests/test_covered_call_pilot_service.py backend/tests/test_covered_call_execution.py backend/tests/test_covered_call_execution_route.py backend/tests/test_covered_call_review.py backend/tests/test_covered_call_review_route.py backend/tests/test_trade_executor_snapshot_guard.py -q`
- [ ] Run:
  `python -m py_compile backend/app/services/trade_option_models.py backend/app/services/covered_call_execution.py backend/app/services/covered_call_review.py backend/app/routes/trade.py backend/app/schemas.py`
- [ ] Restart backend:
  `systemctl --user restart stocklean-backend && systemctl --user status stocklean-backend --no-pager`
- [ ] HTTP verify:
  - `POST /api/trade/options/covered-call/review` with `{"mode":"live","symbol":"AAPL","dry_run":true}` -> `400 paper_only`
  - `POST /api/trade/options/covered-call/review` with a real paper-held sub-100 symbol -> `blocked` with artifact paths
