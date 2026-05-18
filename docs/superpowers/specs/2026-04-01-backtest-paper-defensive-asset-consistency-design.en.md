# Backtest and Paper Defensive Asset Consistency Design

## Background
The system currently has three related but not fully aligned paths:

1. Lean backtest strategy in `algorithms/ml_overlay_scores.py`
2. Decision snapshot generation in `scripts/universe_pipeline.py` and `backend/app/services/decision_snapshot.py`
3. Paper/live execution in `backend/app/services/trade_execution_targets.py` and `backend/app/services/trade_executor.py`

The latest `run 1162 / snapshot 102` exposed two inconsistencies:

- `snapshot_summary.csv` entered `risk_off`, but persisted `risk_off_symbol=''` and `risk_off_selection='defensive_missing'`
- the paper executor then fell back to default `SGOV` and placed orders anyway

This means the system is not operating with one shared semantic model. Snapshot generation can fail to resolve the defensive asset, and execution applies a second fallback rule later.

## Root Cause
### 1. Snapshot pipeline does not load defensive or idle assets into the price matrix
`scripts/universe_pipeline.py` currently builds `prices/trade_prices` only from the stock universe. If `risk_off_symbols` or `benchmark` are outside the universe, they never enter the price matrix.

As a result:
- `_pick_risk_off_symbol()` cannot choose from the defensive basket
- `idle_allocation=defensive/benchmark` cannot resolve an `idle_symbol`

This produces snapshot rows with empty `risk_off_symbol`, empty `idle_symbol`, and `risk_off_selection=defensive_missing`.

### 2. Snapshot defensive selection logic does not match Lean
Lean strategy semantics are:
- if `risk_off_symbols` is present, choose from that basket using `best_momentum` or `lowest_vol`
- only fall back to `risk_off_symbol` when the basket is empty

The pipeline currently short-circuits to `risk_off_symbol` first when it exists in the matrix. That bypasses basket selection and diverges from Lean.

### 3. Paper/live risk-on execution ignores idle allocation
Lean backtest fills residual exposure in risk-on mode when `idle_allocation != none`.
Paper/live currently reads only `decision_items.csv` for `risk_off=false`, so residual capital remains cash instead of moving into the configured idle asset.

## Goal
Unify all three paths so that:

1. defensive asset selection matches Lean semantics
2. decision snapshots persist effective `risk_off_symbol`, `risk_off_selection`, `idle_symbol`, and `idle_weight`
3. paper/live execution consumes snapshot semantics instead of inventing a different answer at execution time
4. `risk_on + idle_allocation` matches Lean outcomes
5. old snapshots remain compatible, but newly generated snapshots must be complete

## Recommended Approach
Use one shared selection model and fix both snapshot generation and execution.

### Option A: Fix executor only
- Minimal code change
- Leaves snapshot artifacts inconsistent and preserves two semantic models

### Option B: Fix snapshot generation and executor together (recommended)
- Snapshot generation persists the effective defensive and idle symbols
- Executor consumes those persisted semantics
- Old snapshots get a controlled compatibility fallback

### Option C: Re-run Lean before every trade batch
- Most consistent in theory
- Too heavy and unnecessary for this problem

## Design
### 1. Shared defensive/idle symbol resolver
Create a shared helper that receives:
- snapshot or rebalance date
- `risk_off_mode`
- `risk_off_symbol`
- `risk_off_symbols`
- `risk_off_pick`
- `risk_off_lookback_days`
- `idle_allocation_mode`
- `benchmark`

Data source remains local adjusted daily data in `data_root/curated_adjusted`.

Resolution rules:
- if `risk_off_symbols` is non-empty, select from the basket
- if the basket is empty, fall back to `risk_off_symbol`
- if `idle_allocation=benchmark`, use the benchmark
- if `idle_allocation=defensive`, use the same defensive picker

### 2. Fix snapshot pipeline
Update `scripts/universe_pipeline.py` so that benchmark and defensive assets are loaded into the price matrix, even when they are not part of the stock selection universe.

These assets are not part of equity ranking. They exist only for:
- benchmark filters
- defensive selection
- idle allocation

Also update `_pick_risk_off_symbol()` to match Lean semantics and ensure `snapshot_summary.csv` persists real values for:
- `risk_off_symbol`
- `risk_off_selection`
- `idle_symbol`
- `idle_weight`

### 3. Fix execution target resolution
Update `trade_execution_targets.py`.

When `risk_off=true`:
- `cash`: liquidate and hold cash
- `benchmark`: buy benchmark at `effective_exposure_cap`
- `defensive/bond/safe`: buy persisted `risk_off_symbol` at `effective_exposure_cap`
- do not fill the remainder into idle assets; Lean `risk_off` also leaves the remainder as cash

When `risk_off=false`:
- build risk weights from `decision_items.csv`
- if `idle_allocation_mode != none`, allocate residual weight to the persisted `idle_symbol`
- for old snapshots with missing fields, compute a compatibility fallback and mark it in metadata

### 4. Compatibility
For historical snapshots:
- allow controlled fallback resolution in execution
- persist metadata flags such as:
  - `compat_fallback_used=true`
  - `compat_missing_fields=[...]`

New snapshots must be complete and should not rely on compatibility paths.

### 5. Audit and validation
Validation must use the same effective target resolution as execution. It should no longer infer risk-off intent only from `decision_items.csv`.

## Testing
- unit tests for defensive basket selection and idle symbol resolution
- unit tests for execution target resolution in both risk-off and risk-on idle-allocation scenarios
- unit tests ensuring snapshot summary persists non-empty effective symbols
- runtime dry-run validation using a fresh preview snapshot

## Acceptance Criteria
The work is complete only when:
1. new risk-off snapshots persist a non-empty `risk_off_symbol`
2. `risk_on + idle_allocation` in paper/live matches Lean semantics
3. `risk_off` in paper/live buys only `effective_exposure_cap` worth of the selected defensive asset and leaves the rest in cash
4. validation uses the same effective targets as execution
5. tests pass and at least one real dry-run confirms behavior
