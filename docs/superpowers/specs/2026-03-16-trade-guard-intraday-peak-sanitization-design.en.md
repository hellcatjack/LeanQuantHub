# Trade Guard Intraday Peak Sanitization Design

## Background

`trade_runs.id=1155` and `1156` were both blocked before order submission by `guard_halted`.

Investigation shows:

- The blocking reason was `max_intraday_drawdown`
- `trade_guard_state.equity_peak` for `2026-03-16` was inflated to `443184.0`
- Actual account equity stayed near `29k`
- `dd_all` and `dd_52w` already filter peak outliers, but `intraday_drawdown` uses `state.equity_peak` directly

This means a corrupted intraday peak can poison the guard state and keep blocking runs for the rest of the day.

## Goal

- Prevent false `max_intraday_drawdown` triggers from corrupted intraday peaks
- Repair poisoned `equity_peak` state automatically
- Auto-unlock halted state when the halt was caused only by the corrupted intraday peak
- Preserve real intraday drawdown protection

## Solution

### 1. Sanitize intraday peak

Add intraday peak normalization in `trade_guard.py`:

- Raw value: `intraday_peak_raw = state.equity_peak`
- Anchor: `max(day_start_equity, peak_52w, adjusted_equity)`
- Upper bound: `anchor * peak_all_outlier_ratio`
- If `intraday_peak_raw` exceeds the bound, use `intraday_peak_sanitized`

`intraday_drawdown` should use `intraday_peak_sanitized`.

### 2. Repair state

When an intraday peak is detected as an outlier:

- Write the sanitized value back into `state.equity_peak`
- Record:
  - `intraday_peak_raw`
  - `intraday_peak_sanitized`
  - `intraday_peak_outlier_filtered`

### 3. Auto-unlock

If:

- The halt reason is only `max_intraday_drawdown`
- Re-evaluation after sanitization produces no risk reasons

then immediately switch the guard state back to `active`, clear cooldown, and record the unlock reason.

## Tests

- Outlier intraday peak no longer causes false `max_intraday_drawdown`
- Sanitization writes corrected `equity_peak` back to state
- Halted state caused only by the outlier is auto-unlocked
- Legitimate intraday drawdown still blocks
