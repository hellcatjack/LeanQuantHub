# Paper Covered Call Receipt Design

## Goal
Add a post-submit receipt reconciliation layer for the `paper-only covered call submit` flow. This layer is read-only and does not place orders.

## Scope
- Add a backend receipt service and route
- Input: `mode/review_id/command_id`
- Data sources:
  - `command_results/<command_id>.json`
  - `open_orders.json`
  - `gateway_runtime_health.json`
  - `review_bundle.json`
- Output: a more trustworthy reconciled receipt state

## State Model
- `rejected`
  - `command_result.status` is a reject-like status
- `submitted/open_confirmed`
  - `command_result.status=submitted` and open orders match by `brokerage_ids/tag/underlying_symbol`
- `submitted/submitted_unconfirmed`
  - `command_result.status=submitted` but no current open-order match exists
- `submitted/open_orders_stale`
  - submitted, but the open-orders snapshot is stale
- `pending/pending_no_result`
  - no command result yet
- `pending/pending_runtime_unhealthy`
  - no command result yet and runtime is unhealthy

## API
- `POST /api/trade/options/covered-call/receipt`
- `mode=paper` only

## Error Handling
- `paper_only` -> 400
- `review_id_required` -> 400
- `command_id_required` -> 400
- `review_not_found` / `review_bundle_invalid` -> 409

## Audit and Artifacts
- Artifact directory: `artifacts/options_receipt_<timestamp>/summary.json`
- No DB persistence in v1; JSON artifact only

## Non-Goals
- No real option modify/cancel
- No frontend UI
- No live mode
