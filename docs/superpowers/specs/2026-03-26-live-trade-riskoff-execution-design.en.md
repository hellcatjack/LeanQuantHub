# Live Trade Risk-Off Execution Alignment Design

## Summary
Backtests and live/paper execution currently diverge for `risk_off` behavior. The Lean algorithm buys a single selected defensive asset (`RiskOff_Symbol`) at the exposure cap, while the executor either relies on `decision_items.csv` or, in diagnostic mode, equal-weights the entire defensive basket.

## Recommended Approach
Add a snapshot execution target resolver in `trade_executor.py`.

- If `risk_off=false`, keep using `decision_items.csv`.
- If `risk_off=true` and mode is `defensive/bond/safe`, buy only the resolved `risk_off_symbol` at `effective_exposure_cap`.
- If mode is `benchmark`, buy the benchmark symbol at the exposure cap.
- If mode is `cash`, generate no long target weights and let delta logic liquidate risk assets.

## Why This Approach
- Keeps the Lean strategy as the single source of truth for risk-off selection.
- Minimizes blast radius by changing execution semantics, not the full snapshot generation pipeline.
- Preserves current delta-order generation, position safety checks, and audit structure.

## Required Updates
- `trade_executor.py`: add effective target resolver and use it before order generation.
- `trade_riskoff_validation.py`: validate against effective risk-off targets, not only `decision_items.csv`.
- Tests: defensive, benchmark, cash, and risk-on regression coverage.
