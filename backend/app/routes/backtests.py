from __future__ import annotations

import json
import math
import os
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.core.config import settings
from app.db import get_session
from app.models import (
    AlgorithmVersion,
    BacktestRun,
    Dataset,
    MLPipelineRun,
    MLTrainJob,
    Project,
    ProjectAlgorithmBinding,
    Report,
)
from app.schemas import (
    BacktestCompareItem,
    BacktestCompareRequest,
    BacktestCreate,
    BacktestChartOut,
    BacktestListOut,
    BacktestOut,
    BacktestPageOut,
    BacktestProgressOut,
    BacktestPositionOut,
    BacktestSymbolOut,
    BacktestTradeOut,
    DatasetOut,
)
from app.services.audit_log import record_audit
from app.services.lean_runner import run_backtest
from app.routes.projects import (
    _build_symbol_type_index,
    _build_theme_index,
    _get_data_root,
    _resolve_project_config,
    _resolve_theme_memberships,
    _safe_read_csv,
)
from app.routes.datasets import _dataset_symbol

router = APIRouter(prefix="/api/backtests", tags=["backtests"])

MAX_PAGE_SIZE = 200


def _extract_asset_type_filter(config: dict) -> set[str]:
    asset_types = config.get("asset_types")
    if not asset_types and isinstance(config.get("universe"), dict):
        asset_types = config.get("universe", {}).get("asset_types")
    if not asset_types:
        return set()
    if isinstance(asset_types, str):
        items = [asset_types]
    elif isinstance(asset_types, (list, tuple, set)):
        items = asset_types
    else:
        return set()
    normalized = {str(item).strip().upper() for item in items if str(item).strip()}
    return normalized


def _coerce_pagination(page: int, page_size: int, total: int) -> tuple[int, int, int]:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
    if safe_page > total_pages:
        safe_page = total_pages
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset


def _merge_params(base: dict, override: dict) -> dict:
    if not base:
        return dict(override)
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_params(result[key], value)
        else:
            result[key] = value
    return result


def _extract_pipeline_backtest_params(pipeline: MLPipelineRun) -> dict:
    params = pipeline.params if isinstance(pipeline.params, dict) else {}
    backtest_params = params.get("backtest")
    if isinstance(backtest_params, dict):
        return dict(backtest_params)
    fallback_keys = ("algorithm_parameters", "benchmark", "costs", "risk", "data_folder", "score_csv_path")
    fallback: dict[str, object] = {}
    for key in fallback_keys:
        if key in params:
            fallback[key] = params[key]
    return fallback


def _build_theme_weight_index(config: dict) -> dict[str, float]:
    weights: dict[str, float] = {}
    themes = config.get("themes") or []
    if themes:
        for item in themes:
            key = str(item.get("key", "")).strip()
            if not key:
                continue
            raw_weight = item.get("weight")
            if raw_weight is None:
                continue
            try:
                weights[key] = float(raw_weight)
            except (TypeError, ValueError):
                continue
    else:
        for key, raw_weight in (config.get("weights") or {}).items():
            key = str(key).strip()
            if not key:
                continue
            try:
                weights[key] = float(raw_weight)
            except (TypeError, ValueError):
                continue
    return weights


def _collect_project_symbols(config: dict) -> list[str]:
    theme_index = _build_theme_index(config)
    if not theme_index:
        return []
    data_root = _get_data_root()
    universe_path = data_root / "universe" / "universe.csv"
    rows = _safe_read_csv(universe_path)
    resolved = _resolve_theme_memberships(rows, theme_index)
    asset_filter = _extract_asset_type_filter(config)
    symbol_types = _build_symbol_type_index(rows, config) if asset_filter else {}
    weights = _build_theme_weight_index(config)
    has_weights = bool(weights)
    symbols: set[str] = set()
    for key in theme_index.keys():
        weight = weights.get(key)
        if has_weights and weight is not None and weight <= 0:
            continue
        for symbol in resolved.get(key, set()):
            if asset_filter and symbol_types.get(symbol, "UNKNOWN") not in asset_filter:
                continue
            symbols.add(symbol)
    return sorted(symbols)


def _collect_project_theme_map(config: dict) -> tuple[dict[str, str], dict[str, float]]:
    theme_index = _build_theme_index(config)
    if not theme_index:
        return {}, {}
    data_root = _get_data_root()
    universe_path = data_root / "universe" / "universe.csv"
    rows = _safe_read_csv(universe_path)
    resolved = _resolve_theme_memberships(rows, theme_index)
    asset_filter = _extract_asset_type_filter(config)
    symbol_types = _build_symbol_type_index(rows, config) if asset_filter else {}
    symbol_theme_map: dict[str, str] = {}
    for key, symbols in resolved.items():
        for symbol in symbols:
            if symbol:
                symbol_text = str(symbol).upper()
                if asset_filter and symbol_types.get(symbol_text, "UNKNOWN") not in asset_filter:
                    continue
                symbol_theme_map[symbol_text] = str(key).upper()
    weights = _build_theme_weight_index(config)
    theme_weights = {str(k).upper(): float(v) for k, v in weights.items() if k}
    return symbol_theme_map, theme_weights


def _load_order_events(run_id: int) -> list[dict]:
    results_dir = Path(settings.artifact_root) / f"run_{run_id}" / "lean_results"
    if not results_dir.exists():
        return []
    candidates = list(results_dir.glob("*-order-events.json"))
    if not candidates:
        return []
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
    except json.JSONDecodeError:
        return []
    return []


def _read_progress(log_path: Path) -> tuple[float | None, str | None]:
    if not log_path.exists():
        return None, None
    try:
        with log_path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            offset = max(size - 65536, 0)
            handle.seek(offset)
            text = handle.read().decode("utf-8", errors="ignore")
    except OSError:
        return None, None
    lines = [line for line in text.splitlines() if "[progress]" in line]
    if not lines:
        return None, None
    line = lines[-1]
    marker = line.find("[progress]")
    if marker == -1:
        return None, None
    payload = line[marker + len("[progress]") :].strip()
    parts = payload.split()
    if len(parts) < 2:
        return None, None
    date_text = parts[0]
    percent_text = parts[1].strip().rstrip("%")
    try:
        progress = float(percent_text) / 100.0
    except ValueError:
        return None, None
    progress = min(max(progress, 0.0), 1.0)
    return progress, date_text


def _event_symbol(event: dict) -> str:
    for key in ("symbolValue", "symbolPermtick", "symbol"):
        raw = event.get(key)
        if raw:
            text = str(raw).strip()
            if text:
                return text.split(" ")[0].upper()
    return ""


def _extract_trades(events: list[dict]) -> list[BacktestTradeOut]:
    trades: list[BacktestTradeOut] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if str(event.get("status", "")).lower() != "filled":
            continue
        symbol = _event_symbol(event)
        if not symbol:
            continue
        try:
            time_val = int(float(event.get("time") or 0))
            price = float(event.get("fillPrice") or 0.0)
            quantity = float(event.get("fillQuantity") or 0.0)
        except (TypeError, ValueError):
            continue
        if not time_val or quantity == 0:
            continue
        side = str(event.get("direction") or "").lower()
        trades.append(
            BacktestTradeOut(
                symbol=symbol,
                time=time_val,
                price=price,
                quantity=abs(quantity),
                side="buy" if side == "buy" else "sell",
            )
        )
    trades.sort(key=lambda item: (item.symbol, item.time))
    return trades


def _summarize_symbols(trades: list[BacktestTradeOut]) -> list[BacktestSymbolOut]:
    counts: dict[str, int] = {}
    for trade in trades:
        counts[trade.symbol] = counts.get(trade.symbol, 0) + 1
    return [
        BacktestSymbolOut(symbol=symbol, trades=count)
        for symbol, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _build_positions(trades: list[BacktestTradeOut]) -> list[BacktestPositionOut]:
    if not trades:
        return []
    positions: list[BacktestPositionOut] = []
    position = 0.0
    entry_price = 0.0
    entry_time = 0
    entry_qty = 0.0
    for trade in trades:
        qty = trade.quantity if trade.side == "buy" else -trade.quantity
        prev_position = position
        position += qty
        if prev_position == 0 and position != 0:
            entry_price = trade.price
            entry_time = trade.time
            entry_qty = position
            continue
        if prev_position != 0 and position == 0:
            pnl = (trade.price - entry_price) * (1 if prev_position > 0 else -1)
            positions.append(
                BacktestPositionOut(
                    symbol=trade.symbol,
                    start_time=entry_time,
                    end_time=trade.time,
                    entry_price=entry_price,
                    exit_price=trade.price,
                    quantity=abs(entry_qty),
                    profit=pnl > 0,
                )
            )
            entry_price = 0.0
            entry_time = 0
            entry_qty = 0.0
        if prev_position > 0 and position < 0:
            pnl = (trade.price - entry_price)
            positions.append(
                BacktestPositionOut(
                    symbol=trade.symbol,
                    start_time=entry_time,
                    end_time=trade.time,
                    entry_price=entry_price,
                    exit_price=trade.price,
                    quantity=abs(entry_qty),
                    profit=pnl > 0,
                )
            )
            entry_price = trade.price
            entry_time = trade.time
            entry_qty = position
        if prev_position < 0 and position > 0:
            pnl = (entry_price - trade.price)
            positions.append(
                BacktestPositionOut(
                    symbol=trade.symbol,
                    start_time=entry_time,
                    end_time=trade.time,
                    entry_price=entry_price,
                    exit_price=trade.price,
                    quantity=abs(entry_qty),
                    profit=pnl > 0,
                )
            )
            entry_price = trade.price
            entry_time = trade.time
            entry_qty = position
    return positions


def _resolve_dataset_for_symbol(session, symbol: str) -> Dataset | None:
    if not symbol:
        return None
    target = symbol.strip().upper()
    candidates = session.query(Dataset).all()
    matched: list[Dataset] = []
    for dataset in candidates:
        if _dataset_symbol(dataset).upper() == target:
            matched.append(dataset)
    if not matched:
        return None
    vendor_rank = {"alpha": 0, "stooq": 1, "yahoo": 2}

    def rank(item: Dataset) -> tuple[int, int]:
        vendor = (item.vendor or "").strip().lower()
        freq = (item.frequency or "").strip().lower()
        freq_rank = 0 if "daily" in freq else 1
        return (freq_rank, vendor_rank.get(vendor, 9))

    matched.sort(key=rank)
    return matched[0]


@router.get("", response_model=list[BacktestOut])
def list_backtests():
    with get_session() as session:
        return session.query(BacktestRun).order_by(BacktestRun.id.desc()).all()


@router.get("/page", response_model=BacktestPageOut)
def list_backtests_page(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        total = session.query(BacktestRun).count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        runs = (
            session.query(BacktestRun)
            .order_by(BacktestRun.id.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        run_ids = [run.id for run in runs]
        report_map: dict[int, int] = {}
        if run_ids:
            reports = (
                session.query(Report)
                .filter(Report.run_id.in_(run_ids), Report.report_type == "html")
                .order_by(Report.created_at.desc())
                .all()
            )
            for report in reports:
                if report.run_id not in report_map:
                    report_map[report.run_id] = report.id
        items: list[BacktestListOut] = []
        for run in runs:
            out = BacktestListOut.model_validate(run, from_attributes=True)
            out.report_id = report_map.get(run.id)
            items.append(out)
        return BacktestPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )

@router.post("", response_model=BacktestOut)
def create_backtest(payload: BacktestCreate, background_tasks: BackgroundTasks):
    with get_session() as session:
        project = session.get(Project, payload.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        pipeline_id = payload.pipeline_id
        pipeline = None
        if pipeline_id is not None:
            pipeline = session.get(MLPipelineRun, pipeline_id)
            if not pipeline or pipeline.project_id != payload.project_id:
                raise HTTPException(status_code=404, detail="Pipeline 不存在")
        params = payload.params.copy() if isinstance(payload.params, dict) else {}
        if pipeline is not None:
            pipeline_params = _extract_pipeline_backtest_params(pipeline)
            if pipeline_params:
                params = _merge_params(pipeline_params, params)
        config = _resolve_project_config(session, payload.project_id)
        if not params.get("benchmark"):
            params["benchmark"] = config.get("benchmark") or "SPY"
        algo_params = params.get("algorithm_parameters")
        if not isinstance(algo_params, dict):
            algo_params = {}
        train_job_id = params.get("pipeline_train_job_id")
        if not train_job_id:
            config_train_job_id = config.get("backtest_train_job_id")
            if config_train_job_id not in (None, ""):
                params["pipeline_train_job_id"] = config_train_job_id
                train_job_id = config_train_job_id
        if train_job_id:
            train_job = session.get(MLTrainJob, int(train_job_id))
            if train_job and train_job.project_id == payload.project_id:
                if train_job.output_dir:
                    candidate = Path(train_job.output_dir) / "scores.csv"
                    if candidate.exists():
                        algo_params["score_csv_path"] = str(candidate)
        if not str(algo_params.get("symbols") or "").strip():
            theme_symbols = _collect_project_symbols(config)
            if theme_symbols:
                algo_params["symbols"] = ",".join(theme_symbols)
        if not str(algo_params.get("theme_weights") or "").strip():
            symbol_theme_map, theme_weights = _collect_project_theme_map(config)
            if theme_weights:
                algo_params["theme_weights"] = json.dumps(theme_weights, ensure_ascii=False)
            if symbol_theme_map:
                algo_params["symbol_theme_map"] = json.dumps(
                    symbol_theme_map, ensure_ascii=False
                )
        if not str(algo_params.get("theme_tilt") or "").strip():
            algo_params["theme_tilt"] = "0.5"
        backtest_cfg = (
            config.get("backtest") if isinstance(config.get("backtest"), dict) else {}
        )
        backtest_start = (
            config.get("backtest_start")
            or backtest_cfg.get("start")
            or backtest_cfg.get("start_date")
        )
        backtest_end = (
            config.get("backtest_end") or backtest_cfg.get("end") or backtest_cfg.get("end_date")
        )
        if backtest_start and not str(algo_params.get("backtest_start") or "").strip():
            algo_params["backtest_start"] = str(backtest_start)
        if backtest_end and not str(algo_params.get("backtest_end") or "").strip():
            algo_params["backtest_end"] = str(backtest_end)
        backtest_params = config.get("backtest_params")
        if isinstance(backtest_params, dict):
            for key, value in backtest_params.items():
                if key not in algo_params or str(algo_params.get(key) or "").strip() == "":
                    algo_params[key] = value
        binding = (
            session.query(ProjectAlgorithmBinding)
            .filter(ProjectAlgorithmBinding.project_id == payload.project_id)
            .first()
        )
        algorithm_version_id = payload.algorithm_version_id
        if binding:
            if binding.is_locked:
                if algorithm_version_id and algorithm_version_id != binding.algorithm_version_id:
                    raise HTTPException(status_code=400, detail="项目已锁定算法版本")
                algorithm_version_id = binding.algorithm_version_id
            elif algorithm_version_id is None:
                algorithm_version_id = binding.algorithm_version_id
        if algorithm_version_id:
            algo_version = session.get(AlgorithmVersion, algorithm_version_id)
            if not algo_version:
                raise HTTPException(status_code=404, detail="算法版本不存在")
            if isinstance(algo_version.params, dict):
                for key, value in algo_version.params.items():
                    if key not in algo_params or algo_params.get(key) in (None, ""):
                        algo_params[key] = value
            params["algorithm_version_id"] = algo_version.id
            params["algorithm_id"] = algo_version.algorithm_id
            params["algorithm_version"] = algo_version.version
            if algo_version.language:
                params["algorithm_language"] = algo_version.language
            if algo_version.file_path:
                params["algorithm_path"] = algo_version.file_path
            if algo_version.type_name:
                params["algorithm_type_name"] = algo_version.type_name
        if algo_params:
            params["algorithm_parameters"] = algo_params
        run = BacktestRun(
            project_id=payload.project_id, params=params, pipeline_id=pipeline_id
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        record_audit(
            session,
            action="backtest.create",
            resource_type="backtest",
            resource_id=run.id,
            detail={"project_id": payload.project_id},
        )
        session.commit()

    background_tasks.add_task(run_backtest, run.id)
    return run


@router.get("/{run_id}", response_model=BacktestOut)
def get_backtest(run_id: int):
    with get_session() as session:
        run = session.get(BacktestRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="回测不存在")
        return run


@router.get("/{run_id}/progress", response_model=BacktestProgressOut)
def get_backtest_progress(run_id: int):
    with get_session() as session:
        run = session.get(BacktestRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="回测不存在")
        log_path = Path(settings.artifact_root) / f"run_{run_id}" / "lean_run.log"
        progress, as_of = _read_progress(log_path)
        return BacktestProgressOut(
            run_id=run_id,
            status=run.status,
            progress=progress,
            as_of=as_of,
        )


@router.post("/compare", response_model=list[BacktestCompareItem])
def compare_backtests(payload: BacktestCompareRequest):
    run_ids = [run_id for run_id in payload.run_ids if isinstance(run_id, int)]
    if not run_ids:
        raise HTTPException(status_code=400, detail="回测 ID 不能为空")

    with get_session() as session:
        runs = (
            session.query(BacktestRun, Project.name)
            .join(Project, Project.id == BacktestRun.project_id)
            .filter(BacktestRun.id.in_(run_ids))
            .all()
        )

        found_ids = {run.id for run, _ in runs}
        missing = [run_id for run_id in run_ids if run_id not in found_ids]
        if missing:
            raise HTTPException(status_code=404, detail=f"回测不存在: {missing}")

        id_to_item = {
            run.id: BacktestCompareItem(
                id=run.id,
                project_id=run.project_id,
                project_name=project_name,
                status=run.status,
                metrics=run.metrics,
                created_at=run.created_at,
                ended_at=run.ended_at,
            )
            for run, project_name in runs
        }
        return [id_to_item[run_id] for run_id in run_ids]


@router.get("/{run_id}/chart", response_model=BacktestChartOut)
def get_backtest_chart(run_id: int, symbol: str | None = Query(None)):
    with get_session() as session:
        run = session.get(BacktestRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="回测不存在")
        events = _load_order_events(run_id)
        trades = _extract_trades(events)
        symbol_items = _summarize_symbols(trades)
        selected_symbol = symbol.strip().upper() if symbol else None
        if not selected_symbol:
            selected_symbol = symbol_items[0].symbol if symbol_items else None
        filtered_trades = (
            [trade for trade in trades if trade.symbol == selected_symbol]
            if selected_symbol
            else []
        )
        positions = _build_positions(filtered_trades)
        dataset = _resolve_dataset_for_symbol(session, selected_symbol) if selected_symbol else None
        dataset_out = DatasetOut.model_validate(dataset, from_attributes=True) if dataset else None
        return BacktestChartOut(
            run_id=run_id,
            symbol=selected_symbol,
            symbols=symbol_items,
            trades=filtered_trades,
            positions=positions,
            dataset=dataset_out,
        )
