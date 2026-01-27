# Trade Execution (A+C-1) Integration Design

> Goal: build a verifiable trade loop **without IB API**, while keeping a clean switch point for Lean/IB execution (Mock → Live).

## 1. Background & Scope
- Decision snapshot + TradeRun/TradeOrder/TradeFill tables and UI already exist.
- We need a complete loop for order generation + risk + execution abstraction + state/idempotency.
- No options, no HFT, no real IB execution in this phase.

## 2. Design Principles
- **Single flow, pluggable executors**.
- **Idempotency first**.
- **Auditable and replayable**.
- **Mock-first** to validate logic before IB/Lean.

## 3. Architecture Overview
```
PreTradeRun
  └─ DecisionSnapshot (frozen)
       └─ TradeRun (queued)
            ├─ OrderBuilder
            ├─ RiskEngine
            └─ ExecutionProvider
                ├─ MockExecutionProvider (now)
                └─ LeanExecutionProvider (reserved)
```

## 4. Core Components
### 4.1 OrderBuilder
- Input: weights, portfolio value, cash buffer, lot size.
- Output: standardized orders (side/qty/order_type/limit_price/client_order_id).
- Rule:
  - target_notional = weight × portfolio_value
  - qty = floor(target_notional / price / lot_size) × lot_size
  - trim if cash insufficient

### 4.2 RiskEngine
- Input: orders + risk limits (max order notional, max position ratio, single-name/sector caps).
- Output: pass/block + reasons.
- Failures recorded in `TradeRun.params.risk` and audit log.

### 4.3 ExecutionProvider
Unified interface:
- `prepare(run, snapshot) -> orders`
- `risk_check(run, orders) -> (pass, blocked, reasons)`
- `execute(run, orders, dry_run) -> fills + status`
- `finalize(run, result)`

**MockExecutionProvider**: uses snapshot or fallback prices, writes TradeFill.

**LeanExecutionProvider**: reserved for real IB/Lean execution later.

## 5. State Machine & Idempotency
- TradeRun: `queued → running → done/failed/blocked`
- TradeOrder: `NEW → SUBMITTED → PARTIAL/FILLED/CANCELED/REJECTED`
- Idempotency key: `client_order_id = run_id + symbol + side + model_version`
- Re-run rules:
  - reuse existing orders
  - do not mutate terminal orders

## 6. Error Handling & Rollback
- Validation errors → run `failed` with message.
- Risk blocked → run `blocked` with reason.
- Execution errors:
  - missing price → order `REJECTED`
  - other exceptions → run `failed` with error detail

## 7. Observability & Audit
- Each execution emits `trade_run.execute` audit event
- Captures: snapshot id, risk params, result counts, error reason

## 8. Testing
1) Unit tests: order generation/rounding, risk rules, state transitions, idempotency.
2) Mock integration: snapshot → orders → execution → fills.
3) Regression: re-run same TradeRun, no duplicate orders.

## 9. Acceptance (Mock)
- Re-running TradeRun does not duplicate orders
- Risk blocks are explainable and recorded
- Execution results match audit records

## 10. Non-goals
- No real IB execution in this phase
- No options/HFT

