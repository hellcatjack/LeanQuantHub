# Paper Covered Call Timeline Design

## Goal
Add a read-only timeline query for the `paper-only covered call` pilot so callers can inspect `review -> submit -> receipt` as one audit view.

## Scope
- Add backend aggregation service `covered_call_timeline.py`
- Add endpoint `POST /api/trade/options/covered-call/timeline`
- `paper` only
- Read-only, no new command submission

## Inputs / Outputs
Input:
- `mode`
- `review_id`

Output:
- `status`
- `timeline_state`
- `latest_submit`
- `latest_receipt`
- `stages`
- related artifact paths

## Aggregation Rules
1. Load review baseline from `artifacts/<review_id>/review_bundle.json`
2. Scan `options_submit_*/summary.json` and pick the latest matching `review_id`
3. Scan `options_receipt_*/summary.json` and pick the latest matching `review_id`
4. Precedence: `receipt > submit > review`

## timeline_state Rules
- blocked review: `review_blocked`
- review only: `review_<status>`
- blocked submit: `submit_blocked`
- submitted without receipt: `submit_submitted`
- receipt exists: use `receipt_state`

## Error Handling
- non-paper: `paper_only`
- blank `review_id`: `review_id_required`
- missing review bundle: `review_not_found`

## Tests
- service: review-only, latest submit/receipt aggregation, paper_only
- route: paper_only mapping, payload passthrough
