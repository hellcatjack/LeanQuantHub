from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import datetime
import math
from numbers import Number
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models import DecisionSnapshot, MLTrainJob, MLPipelineRun, Project
from app.routes.projects import (
    _build_theme_config,
    _build_weights_config,
    _resolve_project_config,
)
from app.services.project_symbols import collect_project_theme_map


DECISION_ACTIVE_STATUSES = {"queued", "running"}


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

    if risk_cfg:
        plugins["risk_control"] = risk_cfg
    if plugins:
        weights_cfg["backtest_plugins"] = plugins
    return weights_cfg


def _build_decision_configs(
    project_id: int,
    config: dict[str, Any],
    score_csv_path: str | None,
    snapshot_date: str | None,
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
    weights_payload["output_dir"] = str(output_dir)
    if snapshot_date:
        weights_payload["backtest_start"] = snapshot_date
        pit_rebalance_end = _resolve_pit_rebalance_end(snapshot_date)
        weights_payload["backtest_end"] = pit_rebalance_end or snapshot_date

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
        },
    }


def _extract_algo_params(
    pipeline: MLPipelineRun | None, override: dict[str, Any] | None
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if pipeline and isinstance(pipeline.params, dict):
        backtest = pipeline.params.get("backtest")
        if isinstance(backtest, dict):
            algo = backtest.get("algorithm_parameters")
            if isinstance(algo, dict):
                params.update(algo)
    if isinstance(override, dict):
        params.update(override)
    return params


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
    preview: bool,
) -> dict[str, Any]:
    project = session.get(Project, project_id)
    if not project:
        raise RuntimeError("project_not_found")
    config = _resolve_project_config(session, project_id)

    train_job = session.get(MLTrainJob, train_job_id) if train_job_id else None
    pipeline = session.get(MLPipelineRun, pipeline_id) if pipeline_id else None

    algo_params = _extract_algo_params(pipeline, algorithm_parameters)
    score_csv_path = _resolve_score_csv(train_job, algo_params)

    payload = _build_decision_payload(
        project_id, train_job_id, pipeline_id, snapshot_date, algo_params, preview
    )
    root = payload["artifact_dir"]
    output_dir = payload["output_dir"]
    log_path = payload["log_path"]

    theme_path, weights_path = _build_decision_configs(
        project_id,
        config,
        score_csv_path,
        snapshot_date,
        algo_params,
        output_dir,
    )

    summary = _run_pipeline_backtest(theme_path, weights_path, output_dir, log_path)
    if not summary:
        raise RuntimeError("decision_snapshot_failed")

    snapshot_rows = _read_csv_rows(Path(summary.get("snapshot_summary_path") or ""))
    snapshot_row = _select_snapshot_row(snapshot_rows, snapshot_date)
    if not snapshot_row:
        snapshot_row = {
            "snapshot_date": snapshot_date or "",
            "rebalance_date": snapshot_date or "",
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
        }

    theme_map, theme_weights = collect_project_theme_map(config)
    listing_meta = _load_listing_meta(_resolve_data_root())
    weights_rows = _read_csv_rows(Path(summary.get("weights_path") or ""))
    filters_rows = _read_csv_rows(Path(summary.get("universe_excluded_path") or ""))
    items = _build_items(weights_rows, theme_map, listing_meta, snapshot_row)
    filters = _build_filters(filters_rows, theme_map, listing_meta, snapshot_row)
    filter_counts = _summarize_filters(filters)

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
        "score_csv_path": score_csv_path,
        "algorithm_parameters": algo_params,
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
            preview=False,
        )
        summary = _sanitize_json(result.get("summary"))
        snapshot.status = "success"
        snapshot.summary = summary
        snapshot.artifact_dir = result.get("artifact_dir")
        snapshot.summary_path = result.get("summary_path")
        snapshot.items_path = result.get("items_path")
        snapshot.filters_path = result.get("filters_path")
        snapshot.log_path = result.get("log_path")
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
