from __future__ import annotations

from typing import Any

from app.models import BacktestRun, DecisionSnapshot
from app.routes.projects import PROJECT_CONFIG_TAG, _get_latest_version, _resolve_project_config


def _extract_backtest_algorithm_params(backtest_run: BacktestRun | None) -> dict[str, Any]:
    if not backtest_run or not isinstance(backtest_run.params, dict):
        return {}
    algo = backtest_run.params.get("algorithm_parameters")
    if isinstance(algo, dict):
        return dict(algo)
    backtest_cfg = backtest_run.params.get("backtest")
    if isinstance(backtest_cfg, dict):
        nested = backtest_cfg.get("algorithm_parameters")
        if isinstance(nested, dict):
            return dict(nested)
    return {}


def build_trade_strategy_snapshot(
    session,
    *,
    project_id: int,
    snapshot: DecisionSnapshot | None = None,
) -> dict[str, Any]:
    config = _resolve_project_config(session, project_id)
    version = _get_latest_version(session, project_id, PROJECT_CONFIG_TAG)

    config_backtest_params = config.get("backtest_params") if isinstance(config, dict) else None
    summary = snapshot.summary if snapshot and isinstance(snapshot.summary, dict) else {}
    params = snapshot.params if snapshot and isinstance(snapshot.params, dict) else {}
    backtest_link_status = (
        summary.get("backtest_link_status")
        or params.get("backtest_link_status")
        or None
    )

    bound_backtest_run_id = snapshot.backtest_run_id if snapshot else None
    bound_backtest_run = session.get(BacktestRun, bound_backtest_run_id) if bound_backtest_run_id else None
    bound_algo_params = _extract_backtest_algorithm_params(bound_backtest_run)
    bound_backtest_params = bound_algo_params if bound_algo_params else config_backtest_params
    bound_params_source = "decision_snapshot_backtest_run" if bound_algo_params else "project_config"

    bound_run_params = bound_backtest_run.params if bound_backtest_run and isinstance(bound_backtest_run.params, dict) else {}
    benchmark = bound_run_params.get("benchmark") or (config.get("benchmark") if isinstance(config, dict) else None)
    backtest_start = bound_algo_params.get("backtest_start") or (config.get("backtest_start") if isinstance(config, dict) else None)
    backtest_end = bound_algo_params.get("backtest_end") or (config.get("backtest_end") if isinstance(config, dict) else None)

    return {
        "project_config_version_id": version.id if version else None,
        "project_config_hash": version.content_hash if version else None,
        "project_config_created_at": version.created_at.isoformat() if version else None,
        "backtest_run_id": bound_backtest_run_id,
        "backtest_link_status": backtest_link_status,
        "backtest_params_source": bound_params_source,
        "backtest_params": bound_backtest_params,
        "strategy": config.get("strategy") if isinstance(config, dict) else None,
        "signal_mode": config.get("signal_mode") if isinstance(config, dict) else None,
        "backtest_start": backtest_start,
        "backtest_end": backtest_end,
        "benchmark": benchmark,
    }
