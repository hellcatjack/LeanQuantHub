from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
import math
from numbers import Number
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models import BacktestRun, DecisionSnapshot, MLTrainJob, MLPipelineRun, Project
from app.routes.projects import (
    _build_theme_config,
    _build_weights_config,
    _resolve_project_config,
)
from app.services.project_symbols import collect_project_theme_map
from app.services.trade_execution_targets import (
    _RISK_OFF_DEFENSIVE_MODES,
    _resolve_idle_symbol,
    _select_from_defensive_basket,
)


DECISION_ACTIVE_STATUSES = {"queued", "running"}
_SNAPSHOT_STALE_WARNING_RE = re.compile(r"^snapshot_stale:(?P<age>-?\d+)d>(?P<threshold>\d+)d$")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def resolve_backtest_run_link(
    session,
    *,
    project_id: int,
    pipeline_id: int | None,
    explicit_backtest_run_id: int | None,
) -> tuple[int | None, str]:
    if explicit_backtest_run_id:
        run = session.get(BacktestRun, explicit_backtest_run_id)
        if not run:
            raise ValueError("backtest_run_not_found")
        if run.project_id != project_id:
            raise ValueError("backtest_run_project_mismatch")
        return run.id, "explicit"
    if pipeline_id:
        return None, "current_pipeline"
    return None, "current_project"


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            return [dict(row) for row in reader]
    except OSError:
        return []


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _resolve_pit_rebalance_end(snapshot_date: str | None) -> str | None:
    target = _parse_date(snapshot_date)
    if not target:
        return None
    pit_dir = _resolve_data_root() / "universe" / "pit_weekly"
    pit_path = pit_dir / f"pit_{target.replace('-', '')}.csv"
    if not pit_path.exists():
        return None
    rows = _read_csv_rows(pit_path)
    if not rows:
        return None
    rebalance_dates: list[str] = []
    for row in rows:
        if _parse_date(row.get("snapshot_date")) != target:
            continue
        rebalance = _parse_date(row.get("rebalance_date"))
        if rebalance:
            rebalance_dates.append(rebalance)
    if not rebalance_dates:
        return None
    return sorted(set(rebalance_dates))[-1]


def _iter_pit_snapshot_dates() -> list[str]:
    pit_dir = _resolve_data_root() / "universe" / "pit_weekly"
    if not pit_dir.exists():
        return []
    utc_today = datetime.utcnow().date()
    snapshots: set[str] = set()
    for path in pit_dir.glob("pit_*.csv"):
        stem = path.stem
        parts = stem.split("_", 1)
        if len(parts) != 2:
            continue
        raw = parts[1]
        if len(raw) != 8 or not raw.isdigit():
            continue
        try:
            parsed_date = datetime.strptime(raw, "%Y%m%d").date()
        except ValueError:
            continue
        if parsed_date > utc_today:
            continue
        snapshots.add(parsed_date.isoformat())
    return sorted(snapshots)


def _resolve_latest_pit_snapshot() -> str | None:
    snapshots = _iter_pit_snapshot_dates()
    if not snapshots:
        return None
    return snapshots[-1]


def _resolve_effective_pit_snapshot(snapshot_date: str | None) -> dict[str, Any]:
    requested = _parse_date(snapshot_date) if snapshot_date else None
    snapshots = _iter_pit_snapshot_dates()
    latest = snapshots[-1] if snapshots else None
    if not snapshots:
        return {
            "requested_snapshot_date": requested,
            "effective_snapshot_date": None,
            "latest_snapshot_date": None,
            "fallback_used": requested is not None,
            "fallback_reason": "pit_snapshot_unavailable",
        }

    if not requested:
        return {
            "requested_snapshot_date": None,
            "effective_snapshot_date": latest,
            "latest_snapshot_date": latest,
            "fallback_used": False,
            "fallback_reason": None,
        }

    if requested in snapshots:
        return {
            "requested_snapshot_date": requested,
            "effective_snapshot_date": requested,
            "latest_snapshot_date": latest,
            "fallback_used": False,
            "fallback_reason": None,
        }

    earlier = [value for value in snapshots if value <= requested]
    if earlier:
        return {
            "requested_snapshot_date": requested,
            "effective_snapshot_date": earlier[-1],
            "latest_snapshot_date": latest,
            "fallback_used": True,
            "fallback_reason": "requested_snapshot_unavailable_use_previous",
        }

    return {
        "requested_snapshot_date": requested,
        "effective_snapshot_date": snapshots[0],
        "latest_snapshot_date": latest,
        "fallback_used": True,
        "fallback_reason": "requested_snapshot_before_first_available",
    }


def _resolve_snapshot_stale_days() -> int:
    raw = (os.getenv("DECISION_SNAPSHOT_STALE_DAYS") or "").strip()
    try:
        value = int(raw) if raw else 7
    except (TypeError, ValueError):
        value = 7
    return max(1, value)


def _snapshot_age_days(snapshot_date: str | None, *, today: date | None = None) -> int | None:
    normalized = _parse_date(snapshot_date)
    if not normalized:
        return None
    if today is None:
        today = datetime.utcnow().date()
    try:
        snapshot_day = datetime.strptime(normalized, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (today - snapshot_day).days


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _collect_snapshot_warning_codes(summary: dict[str, Any] | None) -> list[str]:
    if not isinstance(summary, dict):
        return []
    codes: list[str] = []
    raw = summary.get("warnings")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, str):
                continue
            code = item.strip()
            if code and code not in codes:
                codes.append(code)
    if codes:
        return codes

    if summary.get("snapshot_fallback_used"):
        fallback_reason = summary.get("snapshot_fallback_reason")
        if isinstance(fallback_reason, str) and fallback_reason.strip():
            code = fallback_reason.strip()
            if code not in codes:
                codes.append(code)

    if summary.get("snapshot_stale_warning"):
        age = _coerce_int(summary.get("snapshot_age_days"))
        threshold = _coerce_int(summary.get("snapshot_stale_days_threshold"))
        if age is not None and threshold is not None:
            stale_code = f"snapshot_stale:{age}d>{threshold}d"
        else:
            stale_code = "snapshot_stale"
        if stale_code not in codes:
            codes.append(stale_code)
    return codes


def _format_snapshot_warning(code: str, summary: dict[str, Any]) -> str:
    requested_raw = summary.get("requested_snapshot_date")
    effective_raw = summary.get("effective_snapshot_date")
    requested = _parse_date(requested_raw) if isinstance(requested_raw, str) else None
    effective = _parse_date(effective_raw) if isinstance(effective_raw, str) else None
    if code == "requested_snapshot_unavailable_use_previous":
        if requested and effective and requested != effective:
            return f"请求的PIT快照 {requested} 不可用，已自动回退到 {effective}。"
        return "请求的PIT快照不可用，已自动回退到最近可用快照。"
    if code == "requested_snapshot_before_first_available":
        if requested and effective:
            return f"请求日期 {requested} 早于最早可用PIT快照，已自动使用 {effective}。"
        return "请求日期早于最早可用PIT快照，已自动使用最早快照。"
    if code == "pit_snapshot_unavailable":
        return "当前无可用PIT快照，请先完成PIT快照生成。"
    if code.startswith("snapshot_stale"):
        matched = _SNAPSHOT_STALE_WARNING_RE.match(code)
        if matched:
            age_days = _coerce_int(matched.group("age"))
            threshold_days = _coerce_int(matched.group("threshold"))
        else:
            age_days = _coerce_int(summary.get("snapshot_age_days"))
            threshold_days = _coerce_int(summary.get("snapshot_stale_days_threshold"))
        if age_days is not None and threshold_days is not None:
            return (
                f"PIT快照时效告警：当前快照距今{age_days}天，"
                f"超过阈值{threshold_days}天。"
            )
        return "PIT快照时效告警：当前快照已超过时效阈值。"
    return code


def build_snapshot_warning_message(summary: dict[str, Any] | None) -> str | None:
    if not isinstance(summary, dict):
        return None
    warning_codes = _collect_snapshot_warning_codes(summary)
    if not warning_codes:
        return None
    messages: list[str] = []
    for code in warning_codes:
        message = _format_snapshot_warning(code, summary)
        if message and message not in messages:
            messages.append(message)
    if not messages:
        return None
    return "；".join(messages)


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return None


def _normalize_score_path(path: str | None) -> str | None:
    if not path:
        return None
    text = str(path).strip()
    if not text:
        return None
    p = Path(text)
    if not p.is_absolute():
        p = _project_root() / p
    return str(p)


def _load_listing_meta(data_root: Path) -> dict[str, dict[str, str]]:
    path = data_root / "universe" / "alpha_symbol_life.csv"
    rows = _read_csv_rows(path)
    meta: dict[str, dict[str, str]] = {}
    for row in rows:
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        meta[symbol] = {
            "name": (row.get("name") or "").strip(),
            "exchange": (row.get("exchange") or "").strip(),
            "asset_type": (row.get("assetType") or "").strip(),
        }
    return meta


def _select_snapshot_row(
    rows: list[dict[str, str]], snapshot_date: str | None
) -> dict[str, str] | None:
    if not rows:
        return None
    target = _parse_date(snapshot_date) if snapshot_date else None
    if target:
        for row in rows:
            if row.get("snapshot_date") == target:
                return row
    def _row_key(item: dict[str, str]) -> str:
        return item.get("rebalance_date") or item.get("snapshot_date") or ""
    rows_sorted = sorted(rows, key=_row_key)
    return rows_sorted[-1] if rows_sorted else None


def _normalize_snapshot_row(
    row: dict[str, str] | None, fallback_date: str | None
) -> dict[str, str] | None:
    if row is None:
        return None
    normalized = dict(row)
    if fallback_date:
        if not normalized.get("snapshot_date"):
            normalized["snapshot_date"] = fallback_date
        if not normalized.get("rebalance_date"):
            normalized["rebalance_date"] = fallback_date
    return normalized


def _hydrate_snapshot_runtime_fields(
    row: dict[str, str] | None,
    *,
    algo_params: dict[str, Any],
) -> dict[str, str] | None:
    if row is None:
        return None
    normalized = dict(row)
    summary_context: dict[str, Any] = {
        "snapshot_date": normalized.get("snapshot_date"),
        "rebalance_date": normalized.get("rebalance_date"),
        "risk_off": normalized.get("risk_off") == "1",
        "risk_off_mode": normalized.get("risk_off_mode"),
        "risk_off_symbol": normalized.get("risk_off_symbol"),
        "idle_allocation_mode": normalized.get("idle_allocation_mode"),
        "idle_symbol": normalized.get("idle_symbol"),
        "benchmark": normalized.get("benchmark"),
    }
    risk_off_mode = str(normalized.get("risk_off_mode") or "").strip().lower()
    risk_off_selection = str(normalized.get("risk_off_selection") or "").strip().lower()

    if summary_context["risk_off"] and risk_off_mode in _RISK_OFF_DEFENSIVE_MODES:
        risk_off_symbol = str(normalized.get("risk_off_symbol") or "").strip().upper()
        if not risk_off_symbol:
            resolved_symbol, _missing = _select_from_defensive_basket(
                summary=summary_context,
                algo_params=algo_params,
            )
            if resolved_symbol:
                normalized["risk_off_symbol"] = resolved_symbol
                if risk_off_selection in {"", "defensive_missing"}:
                    normalized["risk_off_selection"] = "compat_defensive_pick"

    if not summary_context["risk_off"]:
        idle_mode, idle_symbol, _missing = _resolve_idle_symbol(
            summary=summary_context,
            algo_params=algo_params,
        )
        if idle_mode != "none" and idle_symbol and not str(normalized.get("idle_symbol") or "").strip():
            normalized["idle_symbol"] = idle_symbol
        if idle_mode != "none" and not str(normalized.get("idle_weight") or "").strip():
            try:
                weights_sum = float(normalized.get("weights_sum") or 0.0)
            except (TypeError, ValueError):
                weights_sum = 0.0
            idle_weight = max(0.0, 1.0 - weights_sum)
            if idle_weight > 0.0001:
                normalized["idle_weight"] = f"{idle_weight:.8f}"
    return normalized


def _apply_algorithm_params(weights_cfg: dict[str, Any], algo_params: dict[str, Any]) -> dict[str, Any]:
    plugins = weights_cfg.get("backtest_plugins")
    if not isinstance(plugins, dict):
        plugins = {}
    risk_cfg = plugins.get("risk_control")
    if not isinstance(risk_cfg, dict):
        risk_cfg = {}

    top_n = algo_params.get("top_n")
    if top_n not in (None, ""):
        try:
            weights_cfg["score_top_n"] = int(top_n)
        except (TypeError, ValueError):
            pass
    weighting = algo_params.get("weighting")
    if isinstance(weighting, str) and weighting.strip():
        weights_cfg["score_weighting"] = weighting.strip().lower()
    min_score = algo_params.get("min_score")
    if min_score not in (None, ""):
        weights_cfg["score_min"] = min_score
    max_weight = algo_params.get("max_weight")
    if max_weight not in (None, ""):
        weights_cfg["score_max_weight"] = max_weight
    max_exposure = algo_params.get("max_exposure")
    if max_exposure not in (None, ""):
        risk_cfg["max_exposure"] = max_exposure
        weights_cfg["max_exposure"] = max_exposure
    dynamic_exposure = _coerce_bool(algo_params.get("dynamic_exposure"))
    if dynamic_exposure is not None:
        risk_cfg["dynamic_exposure"] = dynamic_exposure
        weights_cfg["dynamic_exposure"] = dynamic_exposure
    drawdown_tiers = algo_params.get("drawdown_tiers")
    if drawdown_tiers not in (None, ""):
        risk_cfg["drawdown_tiers"] = drawdown_tiers
        weights_cfg["drawdown_tiers"] = drawdown_tiers
    drawdown_exposures = algo_params.get("drawdown_exposures")
    if drawdown_exposures not in (None, ""):
        risk_cfg["drawdown_exposures"] = drawdown_exposures
        weights_cfg["drawdown_exposures"] = drawdown_exposures
    drawdown_exposure_floor = algo_params.get("drawdown_exposure_floor")
    if drawdown_exposure_floor not in (None, ""):
        risk_cfg["drawdown_exposure_floor"] = drawdown_exposure_floor
        weights_cfg["drawdown_exposure_floor"] = drawdown_exposure_floor
    idle_allocation = algo_params.get("idle_allocation")
    if isinstance(idle_allocation, str) and idle_allocation.strip():
        risk_cfg["idle_allocation"] = idle_allocation.strip().lower()
        weights_cfg["idle_allocation"] = idle_allocation.strip().lower()
    score_delay_days = algo_params.get("score_delay_days")
    if score_delay_days not in (None, ""):
        plugins["score_delay_days"] = score_delay_days
    score_smoothing_alpha = algo_params.get("score_smoothing_alpha")
    if score_smoothing_alpha not in (None, ""):
        smoothing = plugins.get("score_smoothing")
        if not isinstance(smoothing, dict):
            smoothing = {}
        smoothing["enabled"] = True
        smoothing["method"] = smoothing.get("method") or "ema"
        smoothing["alpha"] = score_smoothing_alpha
        carry_missing = _coerce_bool(algo_params.get("score_smoothing_carry"))
        if carry_missing is not None:
            smoothing["carry_missing"] = carry_missing
        plugins["score_smoothing"] = smoothing
    retain_top_n = algo_params.get("retain_top_n")
    if retain_top_n not in (None, ""):
        hysteresis = plugins.get("score_hysteresis")
        if not isinstance(hysteresis, dict):
            hysteresis = {}
        hysteresis["enabled"] = True
        hysteresis["retain_top_n"] = retain_top_n
        plugins["score_hysteresis"] = hysteresis
    market_filter = _coerce_bool(algo_params.get("market_filter"))
    if market_filter is not None:
        risk_cfg["enabled"] = True
        risk_cfg["market_filter"] = market_filter
    market_ma_window = algo_params.get("market_ma_window")
    if market_ma_window not in (None, ""):
        risk_cfg["market_ma_window"] = market_ma_window
    risk_off_mode = algo_params.get("risk_off_mode")
    if isinstance(risk_off_mode, str) and risk_off_mode.strip():
        risk_cfg["risk_off_mode"] = risk_off_mode.strip().lower()
        weights_cfg["risk_off_mode"] = risk_off_mode.strip().lower()
    risk_off_pick = algo_params.get("risk_off_pick")
    if isinstance(risk_off_pick, str) and risk_off_pick.strip():
        risk_cfg["risk_off_pick"] = risk_off_pick.strip().lower()
    risk_off_symbols = algo_params.get("risk_off_symbols")
    if isinstance(risk_off_symbols, str) and risk_off_symbols.strip():
        risk_cfg["risk_off_symbols"] = risk_off_symbols.strip()
    risk_off_symbol = algo_params.get("risk_off_symbol")
    if isinstance(risk_off_symbol, str) and risk_off_symbol.strip():
        risk_cfg["risk_off_symbol"] = risk_off_symbol.strip().upper()
    risk_off_lookback_days = algo_params.get("risk_off_lookback_days")
    if risk_off_lookback_days not in (None, ""):
        risk_cfg["risk_off_lookback_days"] = risk_off_lookback_days
    max_turnover_week = algo_params.get("max_turnover_week")
    if max_turnover_week not in (None, ""):
        weights_cfg["turnover_limit"] = max_turnover_week
    cold_start_turnover = algo_params.get("cold_start_turnover")
    if cold_start_turnover not in (None, ""):
        weights_cfg["cold_start_turnover"] = cold_start_turnover

    if risk_cfg:
        plugins["risk_control"] = risk_cfg
    if plugins:
        weights_cfg["backtest_plugins"] = plugins
    return weights_cfg


def _build_decision_configs(
    project_id: int,
    config: dict[str, Any],
    score_csv_path: str | None,
    effective_snapshot_date: str | None,
    algo_params: dict[str, Any],
    output_dir: Path,
) -> tuple[Path, Path]:
    theme_payload = _build_theme_config(config)
    weights_payload = _build_weights_config(config)

    if score_csv_path:
        weights_payload["signal_mode"] = "ml_scores"
        weights_payload["score_csv_path"] = score_csv_path
    else:
        weights_payload["signal_mode"] = weights_payload.get("signal_mode") or "theme_weights"

    weights_payload["record_universe"] = True
    # Decision snapshots are forward-looking: the pit rebalance date can be beyond the last
    # bar in our daily dataset (e.g., Friday snapshot + next Monday rebalance). Allow the
    # pipeline to emit weights without requiring rebalance-date prices to exist yet.
    weights_payload["allow_future_rebalance"] = True
    weights_payload["output_dir"] = str(output_dir)
    if effective_snapshot_date:
        weights_payload["backtest_start"] = effective_snapshot_date
        pit_rebalance_end = _resolve_pit_rebalance_end(effective_snapshot_date)
        weights_payload["backtest_end"] = pit_rebalance_end or effective_snapshot_date

    weights_payload = _apply_algorithm_params(weights_payload, algo_params)

    config_dir = output_dir / "config"
    _ensure_dir(config_dir)
    theme_path = config_dir / "theme_config.json"
    weights_path = config_dir / "weights_config.json"
    theme_path.write_text(
        json.dumps(theme_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    weights_path.write_text(
        json.dumps(weights_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return theme_path, weights_path


def _run_pipeline_backtest(
    theme_path: Path, weights_path: Path, output_dir: Path, log_path: Path
) -> dict[str, Any] | None:
    base_dir = _project_root()
    script_path = base_dir / "scripts" / "universe_pipeline.py"
    if not script_path.exists():
        raise RuntimeError("universe_pipeline.py not found")
    data_root = _resolve_data_root()
    env = {
        **os.environ,
        "DATA_ROOT": str(data_root),
        "THEME_CONFIG_PATH": str(theme_path),
        "WEIGHTS_CONFIG_PATH": str(weights_path),
        "THEMATIC_BACKTEST_OUTPUT_DIR": str(output_dir),
    }
    _ensure_dir(output_dir)
    with log_path.open("w", encoding="utf-8") as handle:
        proc = subprocess.run(
            [sys.executable, str(script_path), "backtest"],
            cwd=str(base_dir),
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
            env=env,
        )
    if proc.returncode != 0:
        return None
    summary_path = output_dir / "summary.json"
    if not summary_path.exists():
        return None
    return json.loads(summary_path.read_text(encoding="utf-8"))


def _build_decision_payload(
    project_id: int,
    train_job_id: int | None,
    pipeline_id: int | None,
    snapshot_date: str | None,
    algo_params: dict[str, Any],
    algo_params_source: str,
    backtest_run_id: int | None,
    backtest_link_status: str | None,
    preview: bool,
) -> dict[str, Any]:
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    suffix = f"preview_{stamp}" if preview else f"run_{stamp}"
    root = Path(settings.artifact_root) / "decision_snapshots" / f"project_{project_id}" / suffix
    output_dir = root / "output"
    _ensure_dir(output_dir)
    log_path = root / "decision_snapshot.log"

    return {
        "artifact_dir": root,
        "output_dir": output_dir,
        "log_path": log_path,
        "snapshot_date": snapshot_date,
        "train_job_id": train_job_id,
        "pipeline_id": pipeline_id,
        "params": {
            "project_id": project_id,
            "train_job_id": train_job_id,
            "pipeline_id": pipeline_id,
            "snapshot_date": snapshot_date,
            "algorithm_parameters": algo_params,
            "algorithm_parameters_source": algo_params_source,
            "backtest_run_id": backtest_run_id,
            "backtest_link_status": backtest_link_status,
        },
    }


def _extract_algo_params(
    pipeline: MLPipelineRun | None,
    override: dict[str, Any] | None,
    backtest_run: BacktestRun | None,
) -> tuple[dict[str, Any], str]:
    params: dict[str, Any] = {}
    backtest_params: dict[str, Any] = {}
    pipeline_params: dict[str, Any] = {}
    override_params: dict[str, Any] = {}

    if backtest_run and isinstance(backtest_run.params, dict):
        algo = backtest_run.params.get("algorithm_parameters")
        if isinstance(algo, dict):
            backtest_params = dict(algo)
        else:
            backtest_cfg = backtest_run.params.get("backtest")
            if isinstance(backtest_cfg, dict):
                nested = backtest_cfg.get("algorithm_parameters")
                if isinstance(nested, dict):
                    backtest_params = dict(nested)

    if pipeline and isinstance(pipeline.params, dict):
        backtest = pipeline.params.get("backtest")
        if isinstance(backtest, dict):
            algo = backtest.get("algorithm_parameters")
            if isinstance(algo, dict):
                pipeline_params = dict(algo)
    if isinstance(override, dict):
        override_params = dict(override)

    if backtest_params:
        params.update(backtest_params)
    if pipeline_params:
        params.update(pipeline_params)
    if override_params:
        params.update(override_params)

    if override_params:
        source = "override"
    elif pipeline_params:
        source = "pipeline"
    elif backtest_params:
        source = "backtest_run"
    else:
        source = "empty"

    return params, source


def _resolve_score_csv(
    train_job: MLTrainJob | None, algo_params: dict[str, Any]
) -> str | None:
    if train_job:
        if train_job.output_dir:
            candidate = Path(str(train_job.output_dir)) / "scores.csv"
            resolved = _normalize_score_path(str(candidate))
            if resolved:
                return resolved
        resolved = _normalize_score_path(train_job.scores_path)
        if resolved:
            return resolved
    score_path = algo_params.get("score_csv_path")
    if isinstance(score_path, str):
        resolved = _normalize_score_path(score_path)
        if resolved:
            return resolved
    return _normalize_score_path("ml/models/scores.csv")


def _score_sort_key(item: dict[str, Any]) -> tuple[int, float, float, str]:
    score = item.get("score")
    weight = item.get("weight")
    symbol = item.get("symbol") or ""
    if score is None:
        return (1, 0.0, -(weight or 0.0), symbol)
    return (0, -float(score), -(weight or 0.0), symbol)


def _build_items(
    rows: list[dict[str, str]],
    theme_map: dict[str, str],
    listing_meta: dict[str, dict[str, str]],
    snapshot_row: dict[str, str],
) -> list[dict[str, Any]]:
    snapshot_date = snapshot_row.get("snapshot_date") or ""
    rebalance_date = snapshot_row.get("rebalance_date") or ""
    items: list[dict[str, Any]] = []
    for row in rows:
        if row.get("snapshot_date") != snapshot_date:
            continue
        if rebalance_date and row.get("rebalance_date") != rebalance_date:
            continue
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        weight_raw = row.get("weight")
        score_raw = row.get("score")
        try:
            weight = float(weight_raw) if weight_raw not in (None, "") else None
        except (TypeError, ValueError):
            weight = None
        try:
            score = float(score_raw) if score_raw not in (None, "") else None
        except (TypeError, ValueError):
            score = None
        listing = listing_meta.get(symbol, {})
        company_name = listing.get("name") or ""
        items.append(
            {
                "symbol": symbol,
                "snapshot_date": snapshot_date,
                "rebalance_date": rebalance_date,
                "company_name": company_name,
                "weight": weight,
                "score": score,
                "theme": theme_map.get(symbol, ""),
            }
        )
    items = sorted(items, key=_score_sort_key)
    for idx, item in enumerate(items, start=1):
        item["rank"] = idx
    return items


def _build_filters(
    rows: list[dict[str, str]],
    theme_map: dict[str, str],
    listing_meta: dict[str, dict[str, str]],
    snapshot_row: dict[str, str],
) -> list[dict[str, Any]]:
    snapshot_date = snapshot_row.get("snapshot_date") or ""
    rebalance_date = snapshot_row.get("rebalance_date") or ""
    items: list[dict[str, Any]] = []
    for row in rows:
        if row.get("snapshot_date") != snapshot_date:
            continue
        if rebalance_date and row.get("rebalance_date") != rebalance_date:
            continue
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        reason = row.get("reason") or ""
        snapshot_price = row.get("snapshot_price")
        price_value = None
        try:
            price_value = float(snapshot_price) if snapshot_price not in (None, "") else None
        except (TypeError, ValueError):
            price_value = None
        listing = listing_meta.get(symbol, {})
        company_name = listing.get("name") or ""
        items.append(
            {
                "symbol": symbol,
                "snapshot_date": snapshot_date,
                "rebalance_date": rebalance_date,
                "company_name": company_name,
                "reason": reason,
                "snapshot_price": price_value,
                "theme": theme_map.get(symbol, ""),
            }
        )
    return items


def _summarize_filters(filters: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in filters:
        raw = str(item.get("reason") or "").strip()
        if not raw:
            continue
        parts = [part.strip() for part in raw.split("|") if part.strip()]
        for part in parts:
            counts[part] = counts.get(part, 0) + 1
    return counts


def generate_decision_snapshot(
    session,
    *,
    project_id: int,
    train_job_id: int | None,
    pipeline_id: int | None,
    snapshot_date: str | None,
    algorithm_parameters: dict[str, Any] | None,
    backtest_run_id: int | None,
    backtest_link_status: str | None,
    preview: bool,
) -> dict[str, Any]:
    project = session.get(Project, project_id)
    if not project:
        raise RuntimeError("project_not_found")
    config = _resolve_project_config(session, project_id)

    train_job = session.get(MLTrainJob, train_job_id) if train_job_id else None
    pipeline = session.get(MLPipelineRun, pipeline_id) if pipeline_id else None
    backtest_run = session.get(BacktestRun, backtest_run_id) if backtest_run_id else None

    algo_params, algo_params_source = _extract_algo_params(
        pipeline,
        algorithm_parameters,
        backtest_run,
    )
    score_csv_path = _resolve_score_csv(train_job, algo_params)
    snapshot_resolution = _resolve_effective_pit_snapshot(snapshot_date)
    effective_snapshot = snapshot_resolution.get("effective_snapshot_date")

    payload = _build_decision_payload(
        project_id,
        train_job_id,
        pipeline_id,
        snapshot_date,
        algo_params,
        algo_params_source,
        backtest_run_id,
        backtest_link_status,
        preview,
    )
    root = payload["artifact_dir"]
    output_dir = payload["output_dir"]
    log_path = payload["log_path"]

    theme_path, weights_path = _build_decision_configs(
        project_id,
        config,
        score_csv_path,
        effective_snapshot,
        algo_params,
        output_dir,
    )

    summary = _run_pipeline_backtest(theme_path, weights_path, output_dir, log_path)
    if not summary:
        raise RuntimeError("decision_snapshot_failed")

    snapshot_rows = _read_csv_rows(Path(summary.get("snapshot_summary_path") or ""))
    snapshot_row = _select_snapshot_row(snapshot_rows, effective_snapshot)
    if not snapshot_row:
        snapshot_row = {
            "snapshot_date": effective_snapshot or "",
            "rebalance_date": effective_snapshot or "",
            "signal_mode": "",
            "score_date": "",
            "active_count": "0",
            "selected_count": "0",
            "risk_off": "0",
            "risk_off_reason": "",
            "risk_off_mode": "",
            "risk_off_symbol": "",
            "cash_weight": "",
            "weights_sum": "",
            "turnover_scale": "",
            "max_exposure": "",
            "effective_exposure_cap": "",
            "exposure_cap_source": "",
            "drawdown_all": "",
            "drawdown_52w": "",
            "drawdown_current": "",
            "drawdown_tier_threshold": "",
            "drawdown_tier_exposure": "",
            "idle_allocation_mode": "",
            "idle_symbol": "",
            "idle_weight": "",
            "risk_off_selection": "",
        }
    snapshot_row = _normalize_snapshot_row(snapshot_row, effective_snapshot) or snapshot_row
    snapshot_row = _hydrate_snapshot_runtime_fields(
        snapshot_row,
        algo_params=algo_params,
    ) or snapshot_row

    theme_map, theme_weights = collect_project_theme_map(config)
    listing_meta = _load_listing_meta(_resolve_data_root())
    weights_rows = _read_csv_rows(Path(summary.get("weights_path") or ""))
    filters_rows = _read_csv_rows(Path(summary.get("universe_excluded_path") or ""))
    items = _build_items(weights_rows, theme_map, listing_meta, snapshot_row)
    filters = _build_filters(filters_rows, theme_map, listing_meta, snapshot_row)
    filter_counts = _summarize_filters(filters)
    effective_summary_snapshot = _parse_date(snapshot_row.get("snapshot_date")) or effective_snapshot
    snapshot_age_days = _snapshot_age_days(effective_summary_snapshot)
    snapshot_stale_days = _resolve_snapshot_stale_days()
    snapshot_is_stale = (
        snapshot_age_days is not None
        and snapshot_age_days > snapshot_stale_days
    )
    warnings: list[str] = []
    fallback_used = bool(snapshot_resolution.get("fallback_used"))
    fallback_reason = snapshot_resolution.get("fallback_reason")
    if fallback_used and isinstance(fallback_reason, str) and fallback_reason:
        warnings.append(fallback_reason)
    if snapshot_is_stale and snapshot_age_days is not None:
        warnings.append(
            f"snapshot_stale:{snapshot_age_days}d>{snapshot_stale_days}d"
        )

    decision_items_path = root / "decision_items.csv"
    decision_filters_path = root / "filter_reasons.csv"
    with decision_items_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "symbol",
                "snapshot_date",
                "rebalance_date",
                "rank",
                "company_name",
                "weight",
                "score",
                "theme",
            ],
        )
        writer.writeheader()
        for item in items:
            writer.writerow(
                {
                    "symbol": item.get("symbol", ""),
                    "snapshot_date": item.get("snapshot_date", ""),
                    "rebalance_date": item.get("rebalance_date", ""),
                    "rank": item.get("rank", ""),
                    "company_name": item.get("company_name", ""),
                    "weight": item.get("weight", ""),
                    "score": item.get("score", ""),
                    "theme": item.get("theme", ""),
                }
            )
    with decision_filters_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "symbol",
                "snapshot_date",
                "rebalance_date",
                "company_name",
                "reason",
                "snapshot_price",
                "theme",
            ],
        )
        writer.writeheader()
        for item in filters:
            writer.writerow(
                {
                    "symbol": item.get("symbol", ""),
                    "snapshot_date": item.get("snapshot_date", ""),
                    "rebalance_date": item.get("rebalance_date", ""),
                    "company_name": item.get("company_name", ""),
                    "reason": item.get("reason", ""),
                    "snapshot_price": item.get("snapshot_price", ""),
                    "theme": item.get("theme", ""),
                }
            )

    summary_payload = {
        "project_id": project_id,
        "train_job_id": train_job_id,
        "pipeline_id": pipeline_id,
        "backtest_run_id": backtest_run_id,
        "backtest_link_status": backtest_link_status or "missing",
        "score_csv_path": score_csv_path,
        "algorithm_parameters": algo_params,
        "algorithm_parameters_source": algo_params_source,
        "requested_snapshot_date": snapshot_resolution.get("requested_snapshot_date"),
        "effective_snapshot_date": effective_summary_snapshot,
        "snapshot_latest_available": snapshot_resolution.get("latest_snapshot_date"),
        "snapshot_fallback_used": fallback_used,
        "snapshot_fallback_reason": fallback_reason,
        "snapshot_age_days": snapshot_age_days,
        "snapshot_stale_days_threshold": snapshot_stale_days,
        "snapshot_stale_warning": snapshot_is_stale,
        "warnings": warnings,
        "snapshot_date": snapshot_row.get("snapshot_date"),
        "rebalance_date": snapshot_row.get("rebalance_date"),
        "as_of_time": f"{snapshot_row.get('snapshot_date') or ''} close",
        "signal_mode": snapshot_row.get("signal_mode"),
        "score_date": snapshot_row.get("score_date"),
        "active_count": int(snapshot_row.get("active_count") or 0),
        "selected_count": len(items),
        "filtered_count": len(filters),
        "risk_off": snapshot_row.get("risk_off") == "1",
        "risk_off_reason": snapshot_row.get("risk_off_reason"),
        "risk_off_mode": snapshot_row.get("risk_off_mode"),
        "risk_off_symbol": snapshot_row.get("risk_off_symbol"),
        "cash_weight": snapshot_row.get("cash_weight"),
        "weights_sum": snapshot_row.get("weights_sum"),
        "turnover_scale": snapshot_row.get("turnover_scale"),
        "max_exposure": snapshot_row.get("max_exposure"),
        "effective_exposure_cap": snapshot_row.get("effective_exposure_cap"),
        "exposure_cap_source": snapshot_row.get("exposure_cap_source"),
        "drawdown_all": snapshot_row.get("drawdown_all"),
        "drawdown_52w": snapshot_row.get("drawdown_52w"),
        "drawdown_current": snapshot_row.get("drawdown_current"),
        "drawdown_tier_threshold": snapshot_row.get("drawdown_tier_threshold"),
        "drawdown_tier_exposure": snapshot_row.get("drawdown_tier_exposure"),
        "idle_allocation_mode": snapshot_row.get("idle_allocation_mode"),
        "idle_symbol": snapshot_row.get("idle_symbol"),
        "idle_weight": snapshot_row.get("idle_weight"),
        "risk_off_selection": snapshot_row.get("risk_off_selection"),
        "filter_counts": filter_counts,
        "theme_weights": theme_weights,
        "source_summary": summary,
    }

    decision_summary_path = root / "decision_summary.json"
    decision_summary_path.write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "artifact_dir": str(root),
        "summary_path": str(decision_summary_path),
        "items_path": str(decision_items_path),
        "filters_path": str(decision_filters_path),
        "summary": summary_payload,
        "items": items,
        "filters": filters,
        "params": payload["params"],
        "log_path": str(log_path),
    }


def _sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_json(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Number) and not isinstance(value, bool):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if math.isfinite(numeric) else None
    return value


def run_decision_snapshot_task(snapshot_id: int) -> None:
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        snapshot = session.get(DecisionSnapshot, snapshot_id)
        if not snapshot or snapshot.status in {"success", "failed", "canceled"}:
            return
        snapshot.status = "running"
        snapshot.started_at = datetime.utcnow()
        session.commit()
        params = snapshot.params or {}
        result = generate_decision_snapshot(
            session,
            project_id=params.get("project_id"),
            train_job_id=params.get("train_job_id"),
            pipeline_id=params.get("pipeline_id"),
            snapshot_date=params.get("snapshot_date"),
            algorithm_parameters=params.get("algorithm_parameters"),
            backtest_run_id=params.get("backtest_run_id"),
            backtest_link_status=params.get("backtest_link_status"),
            preview=False,
        )
        summary = _sanitize_json(result.get("summary"))
        snapshot.status = "success"
        result_params = _sanitize_json(result.get("params") or {})
        existing_params = snapshot.params if isinstance(snapshot.params, dict) else {}
        snapshot.params = _sanitize_json({**existing_params, **result_params})
        snapshot.summary = summary
        snapshot.artifact_dir = result.get("artifact_dir")
        snapshot.summary_path = result.get("summary_path")
        snapshot.items_path = result.get("items_path")
        snapshot.filters_path = result.get("filters_path")
        snapshot.log_path = result.get("log_path")
        snapshot.message = build_snapshot_warning_message(summary)
        snapshot.snapshot_date = (result.get("summary") or {}).get("snapshot_date")
        snapshot.ended_at = datetime.utcnow()
        session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        if snapshot_id:
            snapshot = session.get(DecisionSnapshot, snapshot_id)
            if snapshot:
                snapshot.status = "failed"
                snapshot.message = str(exc)
                snapshot.ended_at = datetime.utcnow()
                session.commit()
    finally:
        session.close()


def build_preview_decision_snapshot(session, payload: dict[str, Any]) -> dict[str, Any]:
    return generate_decision_snapshot(
        session,
        project_id=payload.get("project_id"),
        train_job_id=payload.get("train_job_id"),
        pipeline_id=payload.get("pipeline_id"),
        snapshot_date=payload.get("snapshot_date"),
        algorithm_parameters=payload.get("algorithm_parameters"),
        backtest_run_id=payload.get("backtest_run_id"),
        backtest_link_status=payload.get("backtest_link_status"),
        preview=True,
    )


def load_decision_snapshot_detail(snapshot: DecisionSnapshot) -> dict[str, Any]:
    summary = snapshot.summary or {}
    if snapshot.summary_path and Path(snapshot.summary_path).exists():
        try:
            summary = json.loads(Path(snapshot.summary_path).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = snapshot.summary or {}
    items = []
    if snapshot.items_path and Path(snapshot.items_path).exists():
        for row in _read_csv_rows(Path(snapshot.items_path)):
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            try:
                weight = float(row.get("weight") or 0.0)
            except (TypeError, ValueError):
                weight = None
            try:
                score = float(row.get("score") or 0.0)
            except (TypeError, ValueError):
                score = None
            try:
                rank = int(row.get("rank") or 0)
            except (TypeError, ValueError):
                rank = None
            items.append(
                {
                    "symbol": symbol,
                    "snapshot_date": row.get("snapshot_date") or "",
                    "rebalance_date": row.get("rebalance_date") or "",
                    "company_name": row.get("company_name") or "",
                    "rank": rank,
                    "weight": weight,
                    "score": score,
                    "theme": row.get("theme") or "",
                }
            )
        items = sorted(items, key=_score_sort_key)
        for idx, item in enumerate(items, start=1):
            item["rank"] = idx
    filters = []
    if snapshot.filters_path and Path(snapshot.filters_path).exists():
        for row in _read_csv_rows(Path(snapshot.filters_path)):
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            snapshot_price = row.get("snapshot_price")
            price_value = None
            try:
                price_value = float(snapshot_price) if snapshot_price not in (None, "") else None
            except (TypeError, ValueError):
                price_value = None
            filters.append(
                {
                    "symbol": symbol,
                    "snapshot_date": row.get("snapshot_date") or "",
                    "rebalance_date": row.get("rebalance_date") or "",
                    "company_name": row.get("company_name") or "",
                    "reason": row.get("reason") or "",
                    "snapshot_price": price_value,
                    "theme": row.get("theme") or "",
                }
            )
    return {"summary": summary, "items": items, "filters": filters}
