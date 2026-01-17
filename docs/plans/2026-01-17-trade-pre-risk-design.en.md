# Phase 3.1 Pre‑Trade Risk Control Design (Global Defaults + One‑Run Override)

## Background & Goal
This design completes IBAutoTrade Phase 3.1 (pre‑trade risk control) using **Global Defaults + One‑Run Override** (A‑1). The goal is to enforce a consistent, auditable risk check **before** any order submission: **pass → continue, fail → block and record** with clear provenance.

## Core Principles
- **Single priority rule**: `risk_overrides` take precedence over `risk_defaults`, merged into `risk_effective`.
- **Block‑first**: any triggered rule blocks the run and prevents any order submission.
- **Auditability**: each run stores effective risk params + trigger reasons.

## Data Model
### New configuration (recommended)
- `trade_settings` (new table)
  - `id`
  - `risk_defaults` JSON (global default risk thresholds)
  - `updated_at`
  - API: `GET /api/trade/settings`, `POST /api/trade/settings`

### Run record
- `trade_runs.params` adds:
  - `risk_overrides` (optional, per‑run overrides)
  - `risk_effective` (merged, final values)
  - `risk_blocked` (reasons and counts)

## Risk Fields (minimal set)
- `portfolio_value`: portfolio net value (required for ratio checks)
- `cash_available`: available cash
- `max_order_notional`: per‑order notional cap
- `max_position_ratio`: per‑symbol position ratio cap
- `max_total_notional`: total notional cap per run
- `max_symbols`: max number of orders per run
- `min_cash_buffer_ratio`: minimum cash buffer ratio (e.g. 5%)

## Execution Flow
1. Load `risk_defaults` (global)
2. Merge `risk_overrides` → `risk_effective`
3. After order generation, run risk checks
4. On failure:
   - `trade_run.status = blocked`
   - `trade_run.message` = primary reason (e.g. `risk:max_order_notional`)
   - `trade_run.params.risk_blocked` = `{reasons, blocked_count, risk_effective}`
   - **exit early, no orders submitted**
5. On pass: proceed to order submission

## Error Handling & Edge Cases
- Missing critical inputs (e.g., `portfolio_value` for ratio rules) → block with a missing‑field reason.
- Invalid threshold format (non‑numeric) → block with format error.

## UI/Display Requirements
- Show “global defaults + run overrides + effective values”.
- On block, display trigger reasons and blocked order count clearly.

## Testing Scope (TDD)
- `max_order_notional` exceeded → blocked
- `max_position_ratio` exceeded → blocked
- `max_total_notional` exceeded → blocked
- `min_cash_buffer_ratio` violated → blocked
- missing `portfolio_value` when ratio needed → blocked
- override priority: `overrides` > `defaults`

## Non‑Goals
- Intraday risk management (Phase 3.2)
- Rollback/fallback (Phase 3.3)
