# Paper Covered Call Review Gate Design

**Goal**
Add a dedicated review-and-approval boundary on top of the current `paper-only covered call prepare` flow: freeze pre-submit snapshots, generate a short-lived approval token, and record audit evidence before any future real paper options submission is allowed.

**Decision**
Do not jump to real paper option submission yet. Build a separate `review gate` first:
- `paper` only
- `covered call` only
- `dry-run` only
- single-underlying review bundle
- emit `review_id / approval_token / approval_expires_at`
- write audit logs
- still no real options submission

## Scope
Included:
- single-underlying covered call review gate
- review bundle artifacts
- approval token generation with expiry
- review-level audit logs
- stricter runtime/position/open-order summary checks

Excluded:
- real paper option submission
- live option trading
- DB persistence for tokens
- multi-underlying batch review
- frontend UI

## Recommended Architecture
Add `covered_call_review.py` to:
- call `prepare_covered_call_execution()`
- freeze runtime / position / open-order review summaries
- generate approval token + expiry
- write review artifacts and audit logs

Expose:
- `POST /api/trade/options/covered-call/review`

## State Model
- `blocked`: no token generated
- `review_required`: token generated, risk tags retained
- `ready`: token generated, no risk tags

## Success Criteria
- `prepare` and `review` are separate stages
- review output is auditable and replayable
- approval tokens are time-bounded
- later real paper submit can be attached to this review gate
- still no real options submission in this phase
