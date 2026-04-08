# Paper-Only Covered Call Pilot Design

**Goal**
Add a `paper-only` real-options pilot path to StockLean, without changing the existing stock trading path and without touching `live`, to validate whether covered calls can run in the current system with controlled risk.

**Decision First**
This phase should not connect a real options writing strategy into the main trading path. The recommended minimum scope is:
- `paper` only
- single-leg `covered call` only
- only underlyings with existing round-lot holdings are eligible
- backend capability and rehearsal first; no automatic merge into current stock batch execution
- deliver “eligible underlyings + contract recommendation + dry-run order plan + risk gates” before any real paper execution

---

## 1. Background

Two prerequisites are already in place:
1. Proxy ETF research showed that an options-income direction is worth further study.
2. The current application layer is still equity-centric and does not have options contract, execution, risk, or UI foundations.

Current constraints:
- [trade_order_builder.py](/app/stocklean/backend/app/services/trade_order_builder.py) only models stock-style orders and has no `expiry/strike/right/multiplier` fields.
- [ib_read_session.py](/app/stocklean/backend/app/services/ib_read_session.py) still hardcodes `secType="STK"` for historical requests.
- The current trade UI and manual-order path are stock-oriented.
- The current account and strategy hold many fragmented positions, and many names are below 100 shares, which fails the minimum requirement for covered calls.

So the next robust step is not “do options trading now”, but to build a constrained, observable, reversible `paper-only covered call pilot`.

---

## 2. Scope Boundaries

### In Scope
- options capability pilot in `paper`
- single-leg `covered call`
- candidate generation and dry-run plans from existing holdings only
- IB-backed options chain and contract detail reads
- eligibility checks, liquidity gates, and runtime health gates
- rehearsal outputs and audit artifacts

### Out of Scope
- real options execution in `live`
- `cash-secured put`
- multi-leg spreads, collars, rolling management
- automatic merge into current stock batch execution
- complex options-chain UI
- persistent local historical database for Greeks/IV

### Robustness Principles
- options capability stays off by default and must enter an explicit `paper-only pilot`
- if eligibility is weak, the system should do nothing rather than force a plan
- every options action must be explainable, replayable, and auditable
- any uncertain contract or quote state blocks automatic execution

---

## 3. Approach Comparison

### A. Stay with proxy ETFs only
Pros:
- lowest risk
- no execution-system expansion

Cons:
- cannot validate the robustness of a real options path
- leaves a large gap between proxy research and actual IB options execution

### B. `paper-only` covered call pilot, recommended
Pros:
- controlled scope
- most direct link to current holdings
- clearest risk boundary
- validates real option-chain reads, contract selection, and order modeling

Cons:
- limited by current account structure; eligible names may be few
- still requires new backend options capability

### C. General options execution framework
Pros:
- most complete in the long run

Cons:
- too large for the current stage
- not enough foundation in the current system
- too risky for a robustness-first program

**Recommendation**
Choose B and build a `paper-only covered call pilot` first.

---

## 4. Target Behavior

Given a `paper` account and current holdings, the system should:
- detect which underlyings qualify for covered calls
- screen candidate call contracts for each qualified name
- produce a minimal recommendation with:
  - underlying
  - coverable contracts
  - expiry
  - strike
  - bid/ask/mid
  - estimated premium
  - blocking reasons or risk tags
- generate a dry-run order plan and audit artifacts

System rules:
- if holdings are below 100 shares, or there are open stock/options orders, that underlying is excluded
- if Gateway/IB runtime health is not good, the whole pilot is blocked
- if the option chain is incomplete, quotes are stale, spreads are too wide, or expiries are invalid, mark the name as `ineligible` instead of forcing selection

---

## 5. Architecture

### A. `ib_options_market.py`
Responsibilities:
- read option-chain metadata and contract details from IB
- output normalized option candidates

Suggested capabilities:
- `fetch_option_chain(symbol, mode)`
- `fetch_option_quotes(contracts, mode)`
- `fetch_contract_details(contract_spec, mode)`

This phase is read-only and does not build a historical options store.

### B. `options_eligibility.py`
Responsibilities:
- decide whether covered call is allowed based on holdings, open orders, runtime health, and pilot rules

Core rules:
- holdings must be `>= 100` and only the round-lot portion is coverable
- no recommendation if the underlying already has relevant options exposure or pending stock/options orders
- block everything when `runtime_health != healthy`
- block everything outside `paper`

### C. `covered_call_planner.py`
Responsibilities:
- score candidate calls and output the final recommendation

Minimum contract-selection rules:
- calls only
- DTE target window: `21-45`
- OTM only
- prefer tighter spreads, more reasonable mid prices, and nearer expiries that are not too aggressive
- Greeks are optional in this phase; if IB returns `delta/modelGreeks`, use them as a bonus signal, not a hard dependency

### D. `covered_call_pilot.py`
Responsibilities:
- orchestrate eligibility, chain reads, selection, dry-run planning, and artifact persistence
- provide a unified API result

### E. `trade_option_models.py`
Responsibilities:
- define option contract and dry-run order-plan data structures
- keep them separate from stock order models so the current stock path is not polluted

### Why not reuse the stock order model
[trade_order_builder.py](/app/stocklean/backend/app/services/trade_order_builder.py) is weight-based and equity-oriented. Options orders need at least:
- `underlying_symbol`
- `expiry`
- `strike`
- `right`
- `multiplier`
- `contracts`
- `limit_price`

Pushing those fields into the current stock model would contaminate the main path. The safer approach is to keep a separate model, produce pilot previews and dry-run artifacts first, and only decide later how paper options execution should integrate with order tables.

---

## 6. Data Flow

### Read Path
1. read current `paper` stock holdings
2. read open orders and filter names with pending actions
3. read Gateway/Bridge runtime health
4. fetch option-chain and quotes for eligible names
5. apply contract-selection rules
6. produce recommendation and dry-run plan

### Output Path
Outputs should include:
- `eligible_underlyings`
- `rejected_underlyings`
- `candidate_contracts`
- `recommended_contracts`
- `dry_run_orders`
- `audit_summary`

Suggested artifacts:
- `artifacts/options_pilot_<timestamp>/summary.json`
- `artifacts/options_pilot_<timestamp>/candidates.json`
- `artifacts/options_pilot_<timestamp>/dry_run_orders.json`

---

## 7. Risk Gates

### System Gates
Block the whole pilot on any of:
- `mode != paper`
- Gateway/Bridge not `healthy`
- recent probe failure
- stale open-orders sync

### Underlying Gates
Exclude an underlying on any of:
- holdings below `100`
- no round-lot coverable portion
- pending stock orders
- existing related options positions
- empty option chain
- spread too wide
- expiry outside the target window

### Contract Gates
Reject a contract on any of:
- not `CALL`
- not OTM
- missing bid/ask
- `ask <= 0` or `bid < 0`
- `spread / mid` above threshold
- incomplete contract details

---

## 8. API

Suggested read-only pilot endpoint:

### `POST /api/trade/options/covered-call/pilot`
Purpose:
- run one `paper-only covered call pilot`

Request:
```json
{
  "mode": "paper",
  "symbols": ["AAPL", "MSFT"],
  "max_candidates_per_symbol": 5,
  "dte_min": 21,
  "dte_max": 45,
  "max_spread_ratio": 0.15,
  "dry_run": true
}
```

Response:
```json
{
  "mode": "paper",
  "status": "ok",
  "eligible": [
    {
      "symbol": "AAPL",
      "shares": 200,
      "coverable_contracts": 2,
      "recommended": {
        "expiry": "2026-05-15",
        "strike": 230.0,
        "right": "C",
        "contracts": 2,
        "bid": 1.2,
        "ask": 1.3,
        "mid": 1.25
      }
    }
  ],
  "rejected": [
    {
      "symbol": "NVDA",
      "reason": "shares_below_100"
    }
  ],
  "artifacts": {
    "summary": ".../summary.json",
    "orders": ".../dry_run_orders.json"
  }
}
```

This phase supports `dry_run=true` only. If the system later moves into real paper options execution, that should use a separate execution endpoint instead of overloading the pilot endpoint.

---

## 9. Testing

### Unit Tests
At minimum:
- reject holdings below 100 shares
- compute coverable contracts correctly for 200/300 shares
- filter non-OTM or too-wide-spread contracts
- block the whole pilot when runtime health is bad
- keep dry-run output shape stable

### Service Tests
- mock IB option-chain and quote responses
- verify planner returns one deterministic recommendation
- verify artifacts are written correctly

### Runtime Verification
- run the pilot against a real `paper` account
- verify that no real order is sent
- verify recommendations match actual holdings

---

## 10. Success Criteria

This phase is not successful because it places real options trades. It is successful if it can:
- reliably identify covered-call eligibility
- reliably fetch and screen IB option chains
- generate explainable dry-run recommendations
- safely block when Gateway health is degraded
- avoid contaminating the existing stock trading path

Only after those are true should the next phase discuss:
- real `paper` options execution
- integration with order tables
- rolling, close-out, and assignment handling

---

## 11. Default Next Step

The default next step is:
1. implement backend read-only capability for the `paper-only covered call pilot`
2. run several dry-run rehearsals against the real `paper` account
3. only if eligibility, candidate quality, and Gateway gating are trustworthy, move into real paper options execution

Direct `live` work is not recommended at this stage.
