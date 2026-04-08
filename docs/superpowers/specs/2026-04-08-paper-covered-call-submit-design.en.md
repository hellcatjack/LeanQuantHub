# Paper Covered Call Submit Design

**Goal**
Add a real `paper` covered-call submit stage on top of the existing review gate. Submit must require `review_id + approval_token`, re-validate runtime health, positions, open orders, and review expiry, and then route the actual order through the long-lived Lean bridge instead of introducing a separate backend-side direct IB execution path.

**Recommendation**
Extend the existing leader-command submit protocol with a minimal option contract payload for single-leg covered calls.
- `paper` only
- covered call only
- single-leg `SELL CALL` only
- explicit `review_id + approval_token`
- pre-submit runtime / position / open-order revalidation
- actual execution still handled by the long-lived Lean/IB bridge
- do not generalize the stock one-shot execution algorithm into a full options executor in this phase

---

## Why the current stock submit path is insufficient

The stock submit path only supports:
- `symbol`
- `quantity`
- `order_type`
- `limit_price`
- `outside_rth`
- `adaptive_priority`

The Lean consumer also hardcodes:
- `SecurityType.Equity`
- stock `MarketOrder / LimitOrder`

That means a real options submit stage needs more than a new API route. It requires coordinated changes to:
- the Python command writer
- the Lean bridge command parser and submitter
- the command result payload for auditability

---

## Scope

### In scope
- `POST /api/trade/options/covered-call/submit`
- `paper` only
- `dry_run=false` only
- validation of:
  - `review_id`
  - `approval_token`
  - `approval_expires_at`
  - runtime health
  - underlying shares still covering `100 * contracts`
  - no conflicting open option orders for the same underlying
- Python-side option submit command generation
- Lean bridge option command parsing and `PlaceOrder`
- command result polling and submit artifacts
- audit log entries

### Out of scope
- `live` options trading
- generic multi-leg options framework
- naked options, spreads, collars
- frontend UI
- full database schema generalization for options orders
- long-lived token persistence

---

## Recommended architecture

### Python side
Add `covered_call_submit.py` to:
- load the review bundle
- validate token and expiry
- re-check runtime/positions/open orders
- write the option submit command
- poll command results
- produce submit artifacts and audit records

Extend `trade_option_models.py` with submit request/result models.

Extend `lean_bridge_commands.py` so `write_submit_order_command()` can carry minimal option fields:
- `sec_type`
- `underlying_symbol`
- `expiry`
- `strike`
- `right`
- `multiplier`

### Lean side
Extend `LeanBridgeResultHandler.cs`:
- keep the current stock path untouched for non-option commands
- for `sec_type == OPT`, require:
  - `underlying_symbol`
  - `expiry`
  - `strike`
  - `right`
  - `quantity`
- only allow negative quantities for covered-call sell orders
- only allow `LMT`
- construct the option symbol and place the order
- include option contract fields in the command result payload

Do **not** extend `LeanBridgeExecutionAlgorithm.cs` in this phase.
It is a short-lived stock executor and not the right place for this pilot.

---

## Command payload

Example minimal option submit payload:

```json
{
  "command_id": "submit_order_cc_123",
  "type": "submit_order",
  "sec_type": "OPT",
  "underlying_symbol": "AAPL",
  "symbol": "AAPL",
  "expiry": "2026-05-15",
  "strike": 210.0,
  "right": "C",
  "multiplier": 100,
  "quantity": -1,
  "tag": "covered_call:review123",
  "order_type": "LMT",
  "limit_price": 1.25,
  "outside_rth": false,
  "requested_at": "...",
  "expires_at": "...",
  "version": 1
}
```

Constraints:
- `sec_type=OPT` requires the full contract identity
- `quantity` must be negative for sell-to-open covered calls
- only `LMT` is allowed for the option path
- `adaptive_priority` is not used for options in this phase

---

## Failure handling

### Hard block
- non-paper mode
- invalid submit mode for this pilot
- token mismatch or expiry
- unhealthy runtime
- insufficient underlying shares
- conflicting open orders

### Pending outcome
If the command result does not arrive within the bounded wait window, return `timeout_pending` and keep the artifacts for later polling.

### Explicit reject
If the bridge returns statuses like:
- `invalid`
- `expired`
- `unsupported_order_type`
- `option_contract_invalid`
- `place_failed`
- `not_connected`
then submit returns a rejected result with the recorded command outcome.

---

## Success criteria

This phase is complete when:
- `paper-only covered call submit` writes real option submit commands
- Lean bridge consumes them and writes option command results
- token/runtime/position/open-order gates are enforced
- stock submit behavior does not regress
- `live` remains untouched
- the pilot remains isolated from the existing stock trading path
