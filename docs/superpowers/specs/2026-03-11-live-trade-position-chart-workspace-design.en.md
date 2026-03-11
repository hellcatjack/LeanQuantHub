# LiveTrade Position Chart Workspace Design

## Background
The current `LiveTrade` page already supports positions, batch close, per-symbol manual orders, and Gateway runtime status. However, the positions area is still table-centric and lacks a professional chart workspace. Users cannot directly inspect historical price action, volume, recent trade markers, or interval switches from the positions view itself.

The goal is not to add a simple chart widget. The goal is to upgrade the positions area into a professional “positions list + chart workspace” similar to moomoo / Futu-style terminals.

## Goal
- Add a professional chart workspace inside the `LiveTrade` positions card.
- Use `IB historical bars first, local Alpha/curated_adjusted daily fallback` by default.
- Support zoom, drag, crosshair, interval switches, volume, overlays, and BUY/SELL markers.
- Keep chart failures isolated from the positions table and trading controls.
- Allow daily/weekly/monthly local fallback even when the Gateway is degraded.

## Final Layout Decision
Use a right-side professional chart workspace:
- Left: existing positions table acting as the symbol selector.
- Right: a persistent `PositionChartWorkspace` for the selected symbol.
- Desktop: two-column layout.
- Mobile: stacked vertical layout.

## Frontend Boundary
Recommended files:
- `frontend/src/components/trade/PositionChartWorkspace.tsx`
- `frontend/src/components/trade/positionChartTypes.ts`
- `frontend/src/components/trade/positionChartUtils.ts`

Responsibilities:
- selected symbol state
- interval switches: `1m / 5m / 15m / 1h / 1D / 1W / 1M`
- request lifecycle, fallback states, and race protection
- rendering candlesticks, volume, overlays, markers, and status banners

## Backend Boundary
Add a synchronous chart API under `brokerage` instead of using async `history-jobs`:
- `GET /api/brokerage/history/chart`

Recommended backend files:
- modify `backend/app/routes/brokerage.py`
- modify `backend/app/schemas.py`
- modify `backend/app/services/ib_market.py`
- create `backend/app/services/price_chart_history.py`

## Data Source Policy
- `1m / 5m / 15m / 1h`: IB historical bars only
- `1D / 1W / 1M`: IB first, local Alpha/curated_adjusted fallback on failure

Rationale:
- Intraday charts must not be faked from daily data.
- Daily/weekly/monthly charts need a stable local fallback path when HMDS is unavailable.

## API Contract
Request:
```http
GET /api/brokerage/history/chart?symbol=AAPL&interval=1m&mode=paper
```

Response (normalized regardless of source):
```json
{
  "symbol": "AAPL",
  "interval": "1D",
  "source": "ib",
  "fallback_used": false,
  "stale": false,
  "bars": [],
  "markers": [],
  "meta": {
    "currency": "USD",
    "price_precision": 2,
    "last_bar_at": "2026-03-10T20:00:00Z"
  },
  "error": null
}
```

The frontend should only care about:
- `source`
- `fallback_used`
- `bars`
- `markers`
- `error`

## Interval Mapping
Recommended default ranges:
- `1m`: `1 D`
- `5m`: `5 D`
- `15m`: `10 D`
- `1h`: `30 D`
- `1D`: `6 M`
- `1W`: `2 Y`
- `1M`: `5 Y`

The backend should translate the UI interval into:
- IB `barSizeSetting`
- IB `durationStr`
- local daily aggregation granularity

## Local Fallback
Local fallback reads Alpha-adjusted daily bars from `data_root/curated_adjusted`:
- `1D`: direct daily bars
- `1W`: weekly aggregation from daily bars
- `1M`: monthly aggregation from daily bars

## Chart Behavior
Required for the first version:
- mouse wheel zoom
- drag pan
- crosshair
- double-click reset
- interval switching
- volume pane
- MA20 / MA60
- BUY/SELL markers
- OHLC / change info strip

Use `lightweight-charts` and keep the visual style close to a professional trading terminal.

## State Handling
- `IB success`: show `source=IB`
- `IB failure + local fallback success`: show fallback banner
- `intraday interval + IB failure`: show explicit unavailable state
- `symbol switch`: keep old chart visible and overlay a loading mask

## Testing
Backend:
- `backend/tests/test_price_chart_history.py`
- `backend/tests/test_price_chart_history_routes.py`

Frontend:
- `frontend/src/components/trade/PositionChartWorkspace.test.tsx`

E2E:
- `frontend/tests/live-trade-position-chart.spec.ts`

## Acceptance Criteria
- Stable desktop two-column positions workspace
- Intervals: `1m / 5m / 15m / 1h / 1D / 1W / 1M`
- Daily/weekly/monthly local fallback when IB is unavailable
- Explicit unavailable state for intraday intervals without IB history
- Zoom, drag, crosshair, volume, MA20/MA60, and trade markers
