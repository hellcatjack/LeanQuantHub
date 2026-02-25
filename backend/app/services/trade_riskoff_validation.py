from __future__ import annotations

from datetime import datetime
from pathlib import Path
import csv
import json
from typing import Any

from app.models import DecisionSnapshot, TradeOrder, TradeRun


def _coerce_bool(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    text = str(raw or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _parse_symbol_list(raw: object) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for token in text.split(","):
        symbol = token.strip().upper()
        if not symbol or symbol in seen:
            continue
        out.append(symbol)
        seen.add(symbol)
    return out


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _load_snapshot_summary(snapshot: DecisionSnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        return {}
    summary = snapshot.summary if isinstance(snapshot.summary, dict) else {}
    if snapshot.summary_path:
        override = _load_json(Path(snapshot.summary_path))
        if override:
            summary = override
    return summary


def _load_target_symbols(items_path: str | None) -> list[str]:
    if not items_path:
        return []
    path = Path(items_path)
    if not path.exists():
        return []
    symbols: list[str] = []
    seen: set[str] = set()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                symbol = str(row.get("symbol") or "").strip().upper()
                if not symbol or symbol in seen:
                    continue
                seen.add(symbol)
                symbols.append(symbol)
    except OSError:
        return []
    return symbols


def _resolve_trade_run(
    session,
    *,
    run_id: int | None,
    project_id: int | None,
    risk_off_only: bool = False,
) -> TradeRun | None:
    if run_id is not None:
        return session.get(TradeRun, int(run_id))
    query = session.query(TradeRun)
    if project_id is not None:
        query = query.filter(TradeRun.project_id == int(project_id))
    ordered = query.order_by(TradeRun.created_at.desc(), TradeRun.id.desc())
    if not risk_off_only:
        return ordered.first()

    snapshots: dict[int, DecisionSnapshot | None] = {}
    for run in ordered.limit(2000).all():
        snapshot_id = int(run.decision_snapshot_id or 0)
        if snapshot_id <= 0:
            continue
        if snapshot_id not in snapshots:
            snapshots[snapshot_id] = session.get(DecisionSnapshot, snapshot_id)
        summary = _load_snapshot_summary(snapshots.get(snapshot_id))
        if _coerce_bool(summary.get("risk_off")):
            return run
    return None


def validate_trade_run_riskoff_alignment(
    session,
    *,
    run_id: int | None = None,
    project_id: int | None = None,
    risk_off_only: bool = False,
) -> dict[str, Any]:
    run = _resolve_trade_run(
        session,
        run_id=run_id,
        project_id=project_id,
        risk_off_only=risk_off_only,
    )
    if run is None:
        if risk_off_only and run_id is None:
            return {
                "status": "skipped",
                "message": "risk_off_trade_run_not_found",
                "project_id": project_id,
            }
        return {"status": "error", "message": "trade_run_not_found"}

    snapshot = session.get(DecisionSnapshot, run.decision_snapshot_id) if run.decision_snapshot_id else None
    if snapshot is None:
        return {
            "status": "error",
            "message": "decision_snapshot_missing",
            "run_id": run.id,
            "project_id": run.project_id,
        }

    summary = _load_snapshot_summary(snapshot)
    risk_off = _coerce_bool(summary.get("risk_off"))
    risk_off_mode = str(summary.get("risk_off_mode") or "").strip().lower()
    risk_off_symbol = str(summary.get("risk_off_symbol") or "").strip().upper()
    algo_params = summary.get("algorithm_parameters") if isinstance(summary.get("algorithm_parameters"), dict) else {}

    defensive_symbols = []
    seen: set[str] = set()
    for symbol in [risk_off_symbol, *_parse_symbol_list(algo_params.get("risk_off_symbols"))]:
        symbol_norm = str(symbol or "").strip().upper()
        if not symbol_norm or symbol_norm in seen:
            continue
        seen.add(symbol_norm)
        defensive_symbols.append(symbol_norm)

    orders = (
        session.query(TradeOrder)
        .filter(TradeOrder.run_id == run.id)
        .order_by(TradeOrder.id.asc())
        .all()
    )
    buy_symbols = sorted(
        {
            str(order.symbol or "").strip().upper()
            for order in orders
            if str(order.side or "").strip().upper() == "BUY" and float(order.quantity or 0.0) > 0
        }
    )
    sell_symbols = sorted(
        {
            str(order.symbol or "").strip().upper()
            for order in orders
            if str(order.side or "").strip().upper() == "SELL" and float(order.quantity or 0.0) > 0
        }
    )
    target_symbols = _load_target_symbols(snapshot.items_path)

    payload: dict[str, Any] = {
        "status": "pass",
        "run_id": run.id,
        "project_id": run.project_id,
        "snapshot_id": snapshot.id,
        "risk_off": risk_off,
        "risk_off_mode": risk_off_mode,
        "defensive_symbols": defensive_symbols,
        "target_symbols": target_symbols,
        "buy_symbols": buy_symbols,
        "sell_symbols": sell_symbols,
        "checked_at": datetime.utcnow().isoformat(timespec="seconds"),
        "violations": [],
        "warnings": [],
    }

    if not risk_off:
        payload["status"] = "skipped"
        payload["message"] = "risk_off_not_triggered"
        return payload

    violations: list[str] = []
    warnings: list[str] = []
    if not orders:
        warnings.append("no_trade_orders")
    if not target_symbols:
        warnings.append("decision_items_missing")

    target_set = set(target_symbols)
    defensive_set = set(defensive_symbols)
    buy_set = set(buy_symbols)

    if defensive_set and target_set and not target_set.issubset(defensive_set):
        violations.append("target_symbols_not_defensive")
    if defensive_set:
        unexpected_buys = sorted(buy_set - defensive_set)
        if unexpected_buys:
            violations.append("unexpected_buy_symbols")
            payload["unexpected_buy_symbols"] = unexpected_buys
    if target_set:
        buys_not_in_target = sorted(buy_set - target_set)
        if buys_not_in_target:
            violations.append("buy_symbols_not_in_snapshot_targets")
            payload["buy_symbols_not_in_target"] = buys_not_in_target

    payload["violations"] = violations
    payload["warnings"] = warnings
    payload["status"] = "failed" if violations else "pass"
    if payload["status"] == "pass":
        payload["message"] = "risk_off_trade_alignment_ok"
    else:
        payload["message"] = "risk_off_trade_alignment_failed"
    return payload
