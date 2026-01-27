# IB Order Execution Loop Design (Extended)

## Goal
- Build a closed loop: decision snapshot -> order generation -> IB placement -> fill writeback -> run status.
- First release supports MKT + LMT, partial fills, idempotent clientOrderId, and risk blocking.
- Live execution uses IB data; training/backtest remains on Alpha.

## Architecture and Data Flow
1) UI/API triggers execution -> create/get TradeRun.
2) Build TradeOrders from decision snapshot (existing builder).
3) Submit orders to IB; listen to orderStatus/execDetails.
4) Write back TradeOrder/TradeFill; update TradeRun status.
5) Persist model snapshot id and parameter version.

Key points:
- Idempotency: clientOrderId = run_id + symbol + side (unique constraint).
- State machine: NEW -> SUBMITTED -> PARTIAL -> FILLED/CANCELED/REJECTED.
- Partial fills: accumulate fill_quantity and avg_fill_price.

## Error Handling and Risk
- Submit failure: mark REJECTED with reason; run -> degraded.
- Market/connection errors: retry once; non-retryable errors fail and alert.
- Pre-trade risk: block before submit; intraday risk stops remaining orders.
- LMT without price: fallback to MKT or abort (configurable).

## Idempotency and Writeback
- Fixed clientOrderId prevents duplicate orders.
- Writeback includes status, filled_quantity, avg_fill_price, last_error.
- Run status: done/partial/failed/hald, with timestamps.

## Testing and Acceptance
- Unit tests:
  - order validation and generation
  - clientOrderId idempotency
  - partial fill aggregation
- API tests:
  - submit run and fetch status
- Integration tests (Mock IB):
  - orderStatus/execDetails simulation
  - disconnect/timeout -> degraded

Acceptance:
1) MKT/LMT orders traceable
2) Partial fills correctly stored
3) Risk blocks remaining orders
4) Idempotency prevents duplicates

