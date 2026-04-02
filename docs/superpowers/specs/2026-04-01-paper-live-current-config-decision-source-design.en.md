# Paper/Live Decision Snapshot Source Design

## Background
The current `paper/live` decision snapshot flow auto-links to the latest successful project or pipeline backtest when `backtest_run_id` is omitted. That makes live-like executions inherit historical backtest parameters by default instead of using the current project or pipeline configuration.

## Goal
When `backtest_run_id` is not explicitly provided:
- stop auto-linking to historical backtests
- use current pipeline params when `pipeline_id` is present (`backtest_link_status=current_pipeline`)
- otherwise use current project config (`backtest_link_status=current_project`)

Historical backtests remain available only through explicit `backtest_run_id`.

## Scope
- Update backtest link resolution in decision snapshot generation
- Apply the same default rule to both decision routes and pretrade batch generation
- Preserve observability through `backtest_run_id`, `backtest_link_status`, and `algorithm_parameters_source`
