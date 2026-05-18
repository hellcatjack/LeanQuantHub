from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
import json
import os
import re
from typing import Any

from app.core.config import settings
from app.models import DecisionSnapshot


_RISK_OFF_DEFENSIVE_MODES = {"defensive", "bond", "safe"}


def _coerce_bool(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    text = str(raw or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _coerce_non_negative_float(raw: object, *, default: float = 0.0) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = float(default)
    if value < 0:
        return max(0.0, float(default))
    return value


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def _resolve_adjusted_data_root() -> Path:
    return _resolve_data_root() / "curated_adjusted"


def parse_symbol_list(raw: object) -> list[str]:
    candidates: list[object] = []
    if isinstance(raw, str):
        candidates = re.split(r"[,;|\s]+", raw)
    elif isinstance(raw, (list, tuple, set)):
        candidates = list(raw)

    symbols: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        symbol = str(item or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def _normalize_symbol_for_filename(symbol: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", "_", str(symbol or "").strip().upper())
    return cleaned.strip("_")


def _find_latest_price_file(root: Path, symbol: str) -> Path | None:
    if not root.exists():
        return None
    normalized = _normalize_symbol_for_filename(symbol)
    if not normalized:
        return None
    matches = sorted(root.glob(f"*_{normalized}_Daily.csv"))
    if not matches:
        return None
    return matches[-1]


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _coerce_int(raw: object, *, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def _read_adjusted_closes(symbol: str, *, on_or_before: date | None) -> list[tuple[date, float]]:
    path = _find_latest_price_file(_resolve_adjusted_data_root(), symbol)
    if path is None:
        return []
    rows: list[tuple[date, float]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                row_date = _parse_date(row.get("date"))
                if row_date is None:
                    continue
                if on_or_before is not None and row_date > on_or_before:
                    continue
                try:
                    close_value = float(row.get("close") or 0.0)
                except (TypeError, ValueError):
                    continue
                if close_value <= 0:
                    continue
                rows.append((row_date, close_value))
    except OSError:
        return []
    rows.sort(key=lambda item: item[0])
    return rows


def _select_from_defensive_basket(
    *,
    summary: dict[str, Any],
    algo_params: dict[str, Any],
) -> tuple[str, list[str]]:
    compat_missing_fields: list[str] = []
    risk_off_symbol = str(summary.get("risk_off_symbol") or "").strip().upper()
    if not risk_off_symbol:
        compat_missing_fields.append("risk_off_symbol")
    basket = parse_symbol_list(
        summary.get("risk_off_symbols")
        or algo_params.get("risk_off_symbols")
    )
    if not basket and risk_off_symbol:
        basket = [risk_off_symbol]
    if not basket:
        fallback_symbol = str(algo_params.get("risk_off_symbol") or "").strip().upper()
        if fallback_symbol:
            basket = [fallback_symbol]
    if not basket:
        return "", compat_missing_fields
    if len(basket) == 1:
        return basket[0], compat_missing_fields

    lookback_days = max(
        5,
        _coerce_int(
            summary.get("risk_off_lookback_days") or algo_params.get("risk_off_lookback_days"),
            default=20,
        ),
    )
    pick_mode = str(summary.get("risk_off_pick") or algo_params.get("risk_off_pick") or "best_momentum").strip().lower()
    as_of_date = (
        _parse_date(summary.get("snapshot_date"))
        or _parse_date(summary.get("rebalance_date"))
    )

    best_symbol: str | None = None
    best_score: float | None = None
    for symbol in basket:
        rows = _read_adjusted_closes(symbol, on_or_before=as_of_date)
        if len(rows) < 2:
            continue
        closes = [close for _, close in rows[-(lookback_days + 1) :]]
        if len(closes) < 2:
            continue
        returns = [
            closes[idx] / closes[idx - 1] - 1.0
            for idx in range(1, len(closes))
            if closes[idx - 1] > 0
        ]
        if not returns:
            continue
        if pick_mode == "lowest_vol":
            mean = sum(returns) / len(returns)
            variance = sum((item - mean) ** 2 for item in returns) / len(returns)
            score = variance ** 0.5
            if best_score is None or score < best_score:
                best_score = score
                best_symbol = symbol
        else:
            score = closes[-1] / closes[0] - 1.0
            if best_score is None or score > best_score:
                best_score = score
                best_symbol = symbol

    return best_symbol or basket[0], compat_missing_fields


def _resolve_idle_symbol(
    *,
    summary: dict[str, Any],
    algo_params: dict[str, Any],
) -> tuple[str, str, list[str]]:
    idle_mode = str(
        summary.get("idle_allocation_mode") or algo_params.get("idle_allocation") or "none"
    ).strip().lower()
    if idle_mode in _RISK_OFF_DEFENSIVE_MODES:
        symbol = str(summary.get("idle_symbol") or "").strip().upper()
        compat_missing_fields: list[str] = []
        if not symbol:
            compat_missing_fields.append("idle_symbol")
            symbol, basket_missing = _select_from_defensive_basket(summary=summary, algo_params=algo_params)
            compat_missing_fields.extend(
                field for field in basket_missing if field not in compat_missing_fields
            )
        return "defensive", symbol, compat_missing_fields
    if idle_mode in {"benchmark", "index", "spy"}:
        symbol = str(summary.get("idle_symbol") or "").strip().upper()
        compat_missing_fields: list[str] = []
        if not symbol:
            compat_missing_fields.append("idle_symbol")
            symbol = str(algo_params.get("benchmark") or summary.get("benchmark") or "SPY").strip().upper() or "SPY"
        return "benchmark", symbol, compat_missing_fields
    return "none", "", []


def load_snapshot_summary(snapshot: DecisionSnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        return {}
    summary = snapshot.summary if isinstance(snapshot.summary, dict) else {}
    summary_path = getattr(snapshot, "summary_path", None)
    if summary_path:
        path = Path(str(summary_path))
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                summary = payload
    return summary


def build_target_weights_from_items(items: list[dict[str, Any]] | None) -> dict[str, float]:
    target_weights: dict[str, float] = {}
    for item in items or []:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        try:
            weight_value = float(item.get("weight") or 0.0)
        except (TypeError, ValueError):
            continue
        target_weights[symbol] = float(weight_value)
    return target_weights


def _resolve_exposure_cap(summary: dict[str, Any], algo_params: dict[str, Any]) -> float:
    cap_candidates = [
        summary.get("effective_exposure_cap"),
        summary.get("max_exposure"),
        algo_params.get("max_exposure"),
    ]
    exposure_cap = 1.0
    for raw in cap_candidates:
        value = _coerce_non_negative_float(raw, default=-1.0)
        if value >= 0.0:
            exposure_cap = value
            break
    if exposure_cap < 0:
        exposure_cap = 1.0
    return min(exposure_cap, 1.0)


def resolve_snapshot_execution_targets(
    snapshot: DecisionSnapshot,
    items: list[dict[str, Any]] | None,
) -> tuple[dict[str, float], dict[str, Any]]:
    summary = load_snapshot_summary(snapshot)
    algo_params = (
        summary.get("algorithm_parameters")
        if isinstance(summary.get("algorithm_parameters"), dict)
        else {}
    )

    risk_off = _coerce_bool(summary.get("risk_off"))
    if not risk_off:
        target_weights = build_target_weights_from_items(items)
        idle_mode, idle_symbol, compat_missing_fields = _resolve_idle_symbol(
            summary=summary,
            algo_params=algo_params,
        )
        total_weight = sum(max(0.0, float(weight)) for weight in target_weights.values())
        idle_weight = max(0.0, 1.0 - total_weight)
        if idle_mode != "none" and idle_symbol and idle_weight > 0.0001:
            target_weights[idle_symbol] = target_weights.get(idle_symbol, 0.0) + idle_weight
        return target_weights, {
            "source": "decision_items",
            "risk_off": False,
            "decision_snapshot_id": snapshot.id,
            "idle_allocation_mode": idle_mode,
            "idle_symbol": idle_symbol if idle_mode != "none" else None,
            "compat_fallback_used": bool(compat_missing_fields),
            "compat_missing_fields": compat_missing_fields,
            "target_symbols": sorted(target_weights.keys()),
        }

    risk_off_mode = str(summary.get("risk_off_mode") or "").strip().lower() or "cash"
    exposure_cap = _resolve_exposure_cap(summary, algo_params)
    risk_off_symbol = str(summary.get("risk_off_symbol") or "").strip().upper()
    compat_missing_fields: list[str] = []
    if risk_off_mode in _RISK_OFF_DEFENSIVE_MODES and not risk_off_symbol:
        risk_off_symbol, compat_missing_fields = _select_from_defensive_basket(
            summary=summary,
            algo_params=algo_params,
        )
    if not risk_off_symbol and risk_off_mode in _RISK_OFF_DEFENSIVE_MODES:
        risk_off_symbol = str(algo_params.get("risk_off_symbol") or "").strip().upper()
        if risk_off_symbol and "risk_off_symbol" not in compat_missing_fields:
            compat_missing_fields.append("risk_off_symbol")
    benchmark_symbol = str(algo_params.get("benchmark") or summary.get("benchmark") or "SPY").strip().upper() or "SPY"

    target_weights: dict[str, float] = {}
    fallback_to_cash = False
    if risk_off_mode == "benchmark":
        if exposure_cap > 0:
            target_weights[benchmark_symbol] = float(exposure_cap)
    elif risk_off_mode in _RISK_OFF_DEFENSIVE_MODES:
        if risk_off_symbol and exposure_cap > 0:
            target_weights[risk_off_symbol] = float(exposure_cap)
        else:
            fallback_to_cash = True

    return target_weights, {
        "source": "snapshot_risk_off",
        "risk_off": True,
        "risk_off_mode": risk_off_mode,
        "risk_off_symbol": risk_off_symbol,
        "benchmark_symbol": benchmark_symbol if risk_off_mode == "benchmark" else None,
        "exposure_cap": float(exposure_cap),
        "decision_snapshot_id": snapshot.id,
        "fallback_to_cash": fallback_to_cash,
        "compat_fallback_used": bool(compat_missing_fields),
        "compat_missing_fields": compat_missing_fields,
        "target_symbols": sorted(target_weights.keys()),
    }
