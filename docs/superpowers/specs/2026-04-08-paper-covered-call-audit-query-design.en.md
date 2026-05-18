# Paper Covered Call Audit Query Design

## Goal
Add a unified read-only query that aggregates `review / submit / receipt / timeline` into one response for audit and future read-only UI use.

## Scope
- Add backend service `covered_call_audit.py`
- Add endpoint `POST /api/trade/options/covered-call/audit`
- `paper` only
- Read-only, no command submission

## Inputs / Outputs
Input:
- `mode`
- `review_id`

Output:
- `status`
- `timeline_state`
- `review`
- `submit`
- `receipt`
- `timeline`
- related artifact paths

## Aggregation Strategy
1. Reuse the timeline aggregation first
2. Load raw review bundle, submit summary, and receipt summary from timeline artifacts
3. Return a unified audit payload so callers do not need to assemble paths and JSON themselves

## Error Handling
- non-paper: `paper_only`
- blank `review_id`: `review_id_required`
- missing timeline/review bundle: propagate existing errors

## Tests
- service: unified aggregation, missing submit/receipt, paper_only
- route: paper_only mapping, payload passthrough
