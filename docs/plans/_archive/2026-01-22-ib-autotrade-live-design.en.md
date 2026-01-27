# IB Auto-Trade Loop (Paper + Live) Design & Plan

> Goal: With IB API available, deliver **Paper + Live** closed-loop trading (data → signal → risk → execution → monitoring) with single-instance safety, traceability, and rollback.

## 1. Background & Scope
- Based on `docs/todolists/IBAutoTradeTODO.md`: IB PRO account, IB data source, weekly rebalance loop.
- Live/Paper execution uses **IB market data**; training/backtest stays on Alpha.
- Options/HFT are out of scope for the first phase.

## 2. Current State & Gaps
### Available
- LiveTrade UI; IB settings/probe/contract cache/history backfill.
- TradeRun/TradeOrder/TradeFill tables and mock execution loop.
- Pre-trade risk checks and TradeGuard evaluation endpoint.

### Gaps
- **Real order execution missing**: still uses `submit_orders_mock`.
- **Streaming missing**: only writes `_status.json`, no long-running subscriptions or lock.
- **Intraday risk not scheduled**: only manual evaluate endpoint.
- **Rollback & alerts incomplete**.

## 3. Design Goals & Principles
- **Real Paper + Live** execution with the same executor, switching accounts by mode.
- **Single-instance safety** for streaming and execution.
- **Auditable** snapshots, params, orders, fills, alerts.
- **Risk-first**: pre-trade + intraday blocks.
- **Data consistency** via `data/ib/stream` as the source of truth.

## 4. Architecture & Data Flow
```
PreTradeRun -> DecisionSnapshot -> TradeRun(queued)
  -> OrderBuilder -> RiskEngine(pre)
  -> IBOrderExecutor (Paper/Live)
  -> TradeOrder/TradeFill writeback
  -> TradeRun status update

IBStreamRunner (daemon)
  -> data/ib/stream/{symbol}.json
  -> data/ib/stream/_status.json
```

## 5. Components
- **IBStreamRunner**: subscription set (snapshot → project fallback), lock, status/heartbeat, degrade to snapshot/history.
- **IBOrderExecutor**: submit MKT/LMT, handle orderStatus/execDetails, partial fills, idempotent clientOrderId.
- **TradeExecutor**: orchestration only (snapshot → orders → risk → execution).
- **TradeGuard**: scheduled intraday evaluation; stream-first valuation with fallback.

## 6. Error Handling & Rollback
- Connection unavailable → TradeRun `blocked` with reason.
- Missing prices → order `REJECTED`, record `market_data_error`.
- Order rejection → `REJECTED` with reason; run `partial/failed`.
- Roll back to last successful snapshot when execution fails.

## 7. Storage
- `data/ib/stream/{symbol}.json` + `_status.json`.
- DB: `trade_runs`, `trade_orders`, `trade_fills`, `trade_guard_state` (existing).

## 8. Monitoring & Alerts
- UI: connection status, stream status, subscription count, latest runs/orders/fills.
- Telegram: disconnects, order failures, risk triggers, rollbacks.

## 9. Testing & Acceptance
- Unit: order builder, risk, idempotency, partial fill, stream status machine.
- Integration: mock IB order flow + stream degrade + lock conflicts.
- E2E: PreTrade → TradeRun → execution → UI.

**Acceptance (Phase 1)**
1) Paper/Live real orders + fills writeback.
2) Market data source is consistent and traceable.
3) Locks prevent duplicate execution.
4) Risk triggers block orders and alert.
5) Full audit trail for runs/orders/fills.

## 10. Implementation Plan
### Phase 1 (MVP)
- IB Gateway/TWS systemd service
- IBStreamRunner daemon + lock + degrade
- IBOrderExecutor real execution
- UI status updates

### Phase 2 (Risk & Alerts)
- Scheduled intraday guard
- Alerts + rollback
- Live confirmation & safety rails

### Phase 3 (Scheduling)
- Weekly rebalance scheduler
- Idempotent retries
- Metrics/log improvements

## 11. Dependencies & Milestones
- Depends on IB Gateway/TWS availability and Telegram bot.
- Milestones: M1 real Paper/Live, M2 risk+alerts, M3 scheduler.

