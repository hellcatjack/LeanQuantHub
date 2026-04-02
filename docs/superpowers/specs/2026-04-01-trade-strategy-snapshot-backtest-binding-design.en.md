# Trade Strategy Snapshot Backtest Binding Design

Trade runs already execute from `decision_snapshot`, but `trade_run.params.strategy_snapshot` still defaults to current project config. This creates inconsistency when a snapshot is explicitly bound to a historical backtest.

The fix is to build trade-side strategy snapshots from `decision_snapshot.backtest_run_id` when present, and fall back to current project config otherwise. The same helper should be used by both pretrade-created runs and manual `/api/trade/runs` creation.
