# Intraday Risk Management (Phase 3.2) Design

## Goals
- Continuously monitor **intraday** PnL, drawdown, and abnormal events. When thresholds are hit, enter a **protective state** (stop new trading, keep positions).
- Provide auditable risk events and clear UI/alert visibility.
- Valuation **prefers IB** real-time/delayed data with automatic fallback to local pricing and explicit source tagging.

## Non-goals
- No forced liquidation/hedging in this phase (**Action A: stop trading, keep positions**).
- No options/derivatives risk controls.

## Assumptions
- IB API might be unavailable at times, so valuation must support fallback.
- Risk guard must work both **pre-order** and **periodic** checks.

---

## Approach Overview
### 1) Risk Guard State
Add a persistent intraday risk state (suggest table `trade_guard_state` or equivalent):
- `trade_date` / `project_id` / `mode`
- `status`: `active` | `halted`
- `halt_reason`: JSON/text (multi-reason)
- `risk_triggers` / `order_failures` / `market_data_errors`
- `day_start_equity` / `equity_peak` / `last_equity`
- `last_valuation_ts` / `valuation_source`
- `cooldown_until`
- `created_at` / `updated_at`

State transition:
- `active` → any threshold hit → `halted`
- `halted` stays until manual reset (no auto-resume by default)

### 2) Valuation Source (IB primary + local fallback)
- **Primary IB**: real-time/delayed prices + account equity if available.
- **Fallback local**: latest cached prices (`data/ib/stream` or local `prices`).
- Add `valuation_stale_seconds` (e.g., 120s). If IB data is stale, downgrade and set `valuation_source=local`.

### 3) Trigger Thresholds (Option C)
Persist in `trade_settings.risk_defaults`:
- `max_daily_loss`
- `max_intraday_drawdown`
- `max_order_failures`
- `max_market_data_errors`
- `max_risk_triggers`
- `cooldown_seconds`

Rules:
- `daily_loss = (last_equity - day_start_equity) / day_start_equity`
- `drawdown = (last_equity - equity_peak) / equity_peak`
- Any breach → `halted` + record reason

### 4) Action A Behavior
- On trigger: **block new orders**, keep existing positions
- No forced liquidation, no defensive rotation
- UI must clearly show “Protection mode (trading halted)”

---

## Data Flow & Triggers
1) **Pre-order guard**
- Before order creation, call `risk_guard.evaluate()`; if `halted`, block

2) **Periodic monitor** (e.g., every 30–60s)
- Refresh valuation → update `trade_guard_state` → evaluate thresholds
- On trigger, send Telegram alert

3) **Event accumulation**
- Order failures / market data errors increment counters

---

## UI & Alerts
- Live-trade panel displays:
  - status (active/halted)
  - equity / daily loss / drawdown
  - trigger reason + timestamp
  - valuation source (IB/local)
- Telegram alerts: risk trigger, data errors, order failure threshold reached

---

## Testing
- Unit tests:
  - daily loss trigger
  - drawdown trigger
  - event counter trigger
  - IB stale → local fallback
- Integration tests:
  - trigger after simulated errors
  - block orders after halt

---

## Future Extensions
- Add Action B/C (rollback model, defensive basket)
- Auto-switch back to IB valuation when available
