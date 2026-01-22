# IB Market Stream Subscription & Cache Design

> Goal: With IB API available, provide stable L1 streaming quotes for **current project / daily decision snapshot**, and expose a consistent cache as the **single source of truth** for live/paper trading (with snapshot/history fallback when needed).

## Background
- The system already supports IB settings + snapshot/history backfill, but lacks **long‑running streaming subscriptions**.
- Trading execution and risk must consume **consistent** prices to avoid mismatch.

## Goals & Scope
- Subscription scope: **current project + daily decision snapshot** (snapshot preferred; fallback to project theme members).
- Market source: IB L1 (bid/ask/last/volume), fallback to snapshot/history if needed.
- Cache output: `data/ib/stream/{symbol}.json` + `_status.json`.
- Non‑goals: options and intraday historical replay.

## Principles
- **Single instance**: only one streaming instance at a time (JobLock).
- **Data consistency**: execution & risk read from `data/ib/stream`.
- **Graceful fallback**: auto downgrade to snapshot/history with clear source marking.
- **Observability**: status & errors must be queryable and alertable.

---

## Architecture & Data Flow
1) Streaming service runs as a long‑lived background task (or systemd). 
2) Periodically refresh subscription set:
   - If decision snapshot exists → use snapshot symbols.
   - Else fallback to project theme members.
3) Diff the set: subscribe new, unsubscribe removed.
4) IB streaming updates → write `data/ib/stream/{symbol}.json`.
5) On disconnect/no updates → fallback snapshot/history and write same path.

## Subscription Set
- Inputs: `project_id` (required), `decision_snapshot_id` (optional).
- Priority: decision snapshot > project theme members.
- Limit: `max_symbols` to prevent accidental oversubscription.
- Refresh cadence: default 30–60 seconds.

---

## Resilience & Monitoring
### Status
- `connected`: streaming OK.
- `degraded`: fallback in use (IB failure/timeout).
- `disconnected`: service stopped/unavailable.

### Fallback
- IB connection failure or 10s no updates → `degraded`.
- Use snapshot/history; mark `source=ib_snapshot|ib_history`.

### Monitoring & Alerts
- `_status.json` fields:
  - `status`, `last_heartbeat`, `subscribed_symbols`, `ib_error_count`, `last_error`
  - `market_data_type` (realtime/delayed)
- Telegram alerts on `degraded` or `disconnected`.

---

## Storage Format
### `data/ib/stream/{symbol}.json`
```
{
  "symbol": "SPY",
  "timestamp": "2026-01-22T09:31:00Z",
  "source": "ib_stream",
  "bid": 480.1,
  "ask": 480.2,
  "last": 480.15,
  "close": 479.8,
  "volume": 123456,
  "currency": "USD",
  "exchange": "SMART"
}
```

### `data/ib/stream/_status.json`
```
{
  "status": "connected",
  "last_heartbeat": "2026-01-22T09:31:05Z",
  "subscribed_symbols": ["SPY","NVDA"],
  "ib_error_count": 0,
  "last_error": null,
  "market_data_type": "delayed"
}
```

---

## API Design
- `POST /api/ib/stream/start`
  - body: `project_id`, `decision_snapshot_id?`, `refresh_interval_seconds?`, `max_symbols?`
- `POST /api/ib/stream/stop`
- `GET /api/ib/stream/status`

UI (LiveTradePage) add:
- Market stream card: status, subscribed count, last update, Start/Stop actions.

---

## Concurrency & Safety
- Use `JobLock("ib_stream")` to guarantee a single active stream.
- Concurrent start should return `ib_stream_lock_busy`.

---

## Tests & Acceptance
1) **Subscription set**: snapshot preferred, fallback to theme.
2) **Mock mode**: Start → write `data/ib/stream/SPY.json` → status=connected.
3) **Degrade**: simulate disconnect → status=degraded → snapshot/history written.
4) **Lock**: concurrent start → second instance rejected.

Acceptance:
- Quote files update continuously with clear source.
- `trade_guard` can read and value positions.
- UI shows status + subscription count.

---

## Future Extensions
- Account/positions sync for live mode.
- Auto‑link subscription set to latest decision snapshot.
