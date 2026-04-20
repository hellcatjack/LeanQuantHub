from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func

from app.core.config import settings
from app.models import TradeFill, TradeGuardState, TradeOrder, TradeRun, TradeSettings
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_quotes


_DEFAULT_GUARD_RISK_PARAMS: dict[str, float | int] = {
    "max_daily_loss": -0.05,
    "max_intraday_drawdown": 0.08,
    "max_drawdown": 0.08,
    "max_drawdown_52w": 0.12,
    "peak_all_outlier_ratio": 3.0,
    "drawdown_recovery_ratio": 0.9,
    "cooldown_seconds": 900,
}
_IB_GUARD_BASELINE_PNL: dict[tuple[int, str, str], float] = {}
_IB_GUARD_BASELINE_PNL_BY_CURRENCY: dict[tuple[int, str, str], dict[str, float]] = {}
_DRAWDOWN_LOCK_REASONS = {"max_drawdown", "max_drawdown_52w", "drawdown_lock"}


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def _resolve_bridge_root() -> Path:
    return resolve_bridge_root()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    # Lean bridge may emit trailing "Z"; normalize to a form datetime.fromisoformat can parse.
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _pick_price(snapshot: dict[str, Any] | None) -> float | None:
    if not snapshot:
        return None
    for key in ("last", "close", "bid", "ask"):
        value = snapshot.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _resolve_market_timezone() -> ZoneInfo:
    tz_name = str(getattr(settings, "market_timezone", "") or "").strip()
    if not tz_name:
        tz_name = "America/New_York"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("America/New_York")


def _resolve_trade_date(now_utc: datetime | None = None) -> date:
    now = now_utc
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    return now.astimezone(_resolve_market_timezone()).date()


def get_or_create_guard_state(
    session,
    *,
    project_id: int,
    mode: str,
    trade_date: date | None = None,
) -> TradeGuardState:
    trade_date = trade_date or _resolve_trade_date()
    row = (
        session.query(TradeGuardState)
        .filter(
            TradeGuardState.project_id == project_id,
            TradeGuardState.trade_date == trade_date,
            TradeGuardState.mode == mode,
        )
        .one_or_none()
    )
    if row:
        return row
    row = TradeGuardState(project_id=project_id, trade_date=trade_date, mode=mode)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def record_guard_event(
    session,
    *,
    project_id: int,
    mode: str,
    event: str,
    trade_date: date | None = None,
    count: int = 1,
) -> TradeGuardState:
    state = get_or_create_guard_state(session, project_id=project_id, mode=mode, trade_date=trade_date)
    if event == "order_failure":
        state.order_failures = int(state.order_failures or 0) + count
    elif event == "market_data_error":
        state.market_data_errors = int(state.market_data_errors or 0) + count
    state.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(state)
    return state


def _merge_risk_params(defaults: dict[str, Any] | None, overrides: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if isinstance(defaults, dict):
        merged.update(defaults)
    if isinstance(overrides, dict):
        merged.update(overrides)
    return merged


def _normalize_guard_risk_params(raw: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(raw or {})
    try:
        max_daily_loss = float(normalized.get("max_daily_loss"))
    except (TypeError, ValueError):
        max_daily_loss = float(_DEFAULT_GUARD_RISK_PARAMS["max_daily_loss"])
    if not math.isfinite(max_daily_loss):
        max_daily_loss = float(_DEFAULT_GUARD_RISK_PARAMS["max_daily_loss"])
    normalized["max_daily_loss"] = -abs(max_daily_loss)

    try:
        max_intraday_drawdown = float(normalized.get("max_intraday_drawdown"))
    except (TypeError, ValueError):
        max_intraday_drawdown = float(_DEFAULT_GUARD_RISK_PARAMS["max_intraday_drawdown"])
    if not math.isfinite(max_intraday_drawdown):
        max_intraday_drawdown = float(_DEFAULT_GUARD_RISK_PARAMS["max_intraday_drawdown"])
    normalized["max_intraday_drawdown"] = abs(max_intraday_drawdown)

    max_drawdown = _coerce_positive_ratio(normalized.get("max_drawdown"))
    if max_drawdown is None:
        max_drawdown = float(_DEFAULT_GUARD_RISK_PARAMS["max_drawdown"])
    normalized["max_drawdown"] = max_drawdown

    max_drawdown_52w = _coerce_positive_ratio(normalized.get("max_drawdown_52w"))
    if max_drawdown_52w is None:
        max_drawdown_52w = float(_DEFAULT_GUARD_RISK_PARAMS["max_drawdown_52w"])
    normalized["max_drawdown_52w"] = max_drawdown_52w
    normalized["peak_all_outlier_ratio"] = _coerce_peak_all_outlier_ratio(
        normalized.get("peak_all_outlier_ratio"),
        default=float(_DEFAULT_GUARD_RISK_PARAMS["peak_all_outlier_ratio"]),
    )

    normalized["drawdown_recovery_ratio"] = _coerce_recovery_ratio(
        normalized.get("drawdown_recovery_ratio"),
        default=float(_DEFAULT_GUARD_RISK_PARAMS["drawdown_recovery_ratio"]),
    )

    try:
        cooldown_seconds = int(float(normalized.get("cooldown_seconds")))
    except (TypeError, ValueError):
        cooldown_seconds = int(_DEFAULT_GUARD_RISK_PARAMS["cooldown_seconds"])
    normalized["cooldown_seconds"] = max(0, cooldown_seconds)
    return normalized


def _coerce_optional_int(raw: object) -> int | None:
    if raw in (None, ""):
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _coerce_optional_float(raw: object) -> float | None:
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _coerce_optional_bool(raw: object) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if raw in (None, ""):
        return None
    if isinstance(raw, (int, float)):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        return bool(int(value))
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return None


def _normalize_cashflow_adjustment_mode(raw: object) -> str:
    mode = str(raw or "").strip().lower()
    if mode in {"off", "disabled", "disable", "zero", "none"}:
        return "off"
    if mode in {"manual", "fixed"}:
        return "manual"
    return "auto"


def _normalize_currency_map(raw: object) -> dict[str, float]:
    output: dict[str, float] = {}
    if isinstance(raw, dict):
        for raw_key, raw_value in raw.items():
            currency = str(raw_key or "").strip().upper()
            value: float | None = None
            if isinstance(raw_value, dict):
                for key in (
                    "value",
                    "amount",
                    "pnl",
                    "net_liquidation",
                    "unrealized_pnl",
                    "realized_pnl",
                ):
                    value = _coerce_optional_float(raw_value.get(key))
                    if value is not None:
                        break
                if not currency:
                    currency = str(raw_value.get("currency") or raw_value.get("code") or "").strip().upper()
            else:
                value = _coerce_optional_float(raw_value)
            if not currency or value is None:
                continue
            output[currency] = value
        return output
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            currency = str(item.get("currency") or item.get("code") or item.get("ccy") or "").strip().upper()
            value: float | None = None
            for key in (
                "value",
                "amount",
                "pnl",
                "net_liquidation",
                "unrealized_pnl",
                "realized_pnl",
            ):
                value = _coerce_optional_float(item.get(key))
                if value is not None:
                    break
            if not currency or value is None:
                continue
            output[currency] = value
    return output


def _merge_currency_maps(base: dict[str, float], extra: dict[str, float]) -> dict[str, float]:
    output = dict(base)
    for currency, value in extra.items():
        output[str(currency).strip().upper()] = float(value)
    return output


def _sum_currency_map(values: dict[str, float]) -> float:
    return float(sum(float(value) for value in values.values()))


def _compute_market_pnl_from_currency_maps(
    current: dict[str, float],
    baseline: dict[str, float],
) -> float:
    total = 0.0
    for currency in set(current.keys()) | set(baseline.keys()):
        total += float(current.get(currency, 0.0)) - float(baseline.get(currency, 0.0))
    return total


def _baseline_store_path() -> Path:
    return _resolve_data_root() / "state" / "trade_guard_ib_baseline_pnl.json"


def _baseline_store_key(baseline_key: tuple[int, str, str]) -> str:
    project_id, mode, trade_day = baseline_key
    return f"{int(project_id)}|{str(mode)}|{str(trade_day)}"


def _read_baseline_store(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.strip():
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _load_persisted_ib_baseline_entry(
    baseline_key: tuple[int, str, str],
) -> tuple[float | None, dict[str, float]]:
    payload = _read_baseline_store(_baseline_store_path())
    raw = payload.get(_baseline_store_key(baseline_key))
    if isinstance(raw, dict):
        scalar = _coerce_optional_float(raw.get("scalar"))
        by_currency = _normalize_currency_map(raw.get("by_currency"))
        return scalar, by_currency
    scalar = _coerce_optional_float(raw)
    return scalar, {}


def _persist_ib_baseline_entry(
    baseline_key: tuple[int, str, str],
    *,
    scalar: float,
    by_currency: dict[str, float],
) -> None:
    path = _baseline_store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _read_baseline_store(path)
        payload[_baseline_store_key(baseline_key)] = {
            "scalar": float(scalar),
            "by_currency": {currency: float(value) for currency, value in sorted(by_currency.items())},
        }
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temp_path.replace(path)
    except OSError:
        return


def _get_or_init_ib_baseline_pnl_entry(
    baseline_key: tuple[int, str, str],
    *,
    pnl_total: float,
    pnl_by_currency: dict[str, float],
) -> tuple[float, dict[str, float]]:
    current = _coerce_optional_float(_IB_GUARD_BASELINE_PNL.get(baseline_key))
    current_by_currency = _normalize_currency_map(_IB_GUARD_BASELINE_PNL_BY_CURRENCY.get(baseline_key) or {})
    if current is not None:
        return current, current_by_currency
    persisted_scalar, persisted_by_currency = _load_persisted_ib_baseline_entry(baseline_key)
    if persisted_scalar is not None:
        _IB_GUARD_BASELINE_PNL[baseline_key] = persisted_scalar
        _IB_GUARD_BASELINE_PNL_BY_CURRENCY[baseline_key] = dict(persisted_by_currency)
        return persisted_scalar, persisted_by_currency
    baseline = float(pnl_total)
    baseline_by_currency = _normalize_currency_map(pnl_by_currency)
    _IB_GUARD_BASELINE_PNL[baseline_key] = baseline
    _IB_GUARD_BASELINE_PNL_BY_CURRENCY[baseline_key] = dict(baseline_by_currency)
    _persist_ib_baseline_entry(
        baseline_key,
        scalar=baseline,
        by_currency=baseline_by_currency,
    )
    return baseline, baseline_by_currency


def _coerce_positive_ratio(raw: object) -> float | None:
    value = _coerce_optional_float(raw)
    if value is None:
        return None
    return abs(value)


def _coerce_peak_all_outlier_ratio(raw: object, *, default: float = 3.0) -> float:
    value = _coerce_optional_float(raw)
    if value is None:
        return float(default)
    # This ratio guards against stale or corrupted all-time peaks.
    if value <= 1.0:
        return float(default)
    return float(value)


def _coerce_recovery_ratio(raw: object, *, default: float = 0.9) -> float:
    value = _coerce_optional_float(raw)
    if value is None:
        return float(default)
    if value <= 0 or value > 1:
        return float(default)
    return value


def _extract_reason_list(reason_payload: object) -> list[str]:
    if not isinstance(reason_payload, dict):
        return []
    raw = reason_payload.get("reasons")
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            output.append(text)
    return output


def _is_drawdown_lock_active(state: TradeGuardState) -> bool:
    if str(state.status or "").strip().lower() != "halted":
        return False
    return any(reason in _DRAWDOWN_LOCK_REASONS for reason in _extract_reason_list(state.halt_reason))


def _try_unlock_non_drawdown_halt(
    state: TradeGuardState,
    *,
    now: datetime,
    unlock_reason: str,
    metrics: dict[str, Any],
    thresholds: dict[str, Any],
    ignore_cooldown: bool = False,
) -> bool:
    if str(state.status or "").strip().lower() != "halted":
        return False
    if _is_drawdown_lock_active(state):
        return False
    # Keep manual/operator halts sticky. Auto-unlock only applies to risk-triggered halts
    # that were recorded with the standard `reasons` payload.
    reason_list = _extract_reason_list(state.halt_reason)
    if not reason_list:
        return False
    cooldown_until = state.cooldown_until
    if not ignore_cooldown and cooldown_until is not None and cooldown_until > now:
        return False
    state.status = "active"
    state.cooldown_until = None
    state.halt_reason = {
        "unlock_reason": unlock_reason,
        "unlocked_at": now.isoformat(timespec="seconds"),
        "metrics": metrics,
        "thresholds": thresholds,
    }
    return True


def _sanitize_intraday_peak(
    raw_peak: float | None,
    *,
    day_start_equity: float | None,
    current_equity: float,
    peak_52w: float | None,
    outlier_ratio: float,
) -> dict[str, float | bool | None]:
    anchor_candidates = []
    if day_start_equity is not None and float(day_start_equity) > 0:
        anchor_candidates.append(float(day_start_equity))
    if peak_52w is not None and float(peak_52w) > 0:
        anchor_candidates.append(float(peak_52w))
    if current_equity > 0:
        anchor_candidates.append(float(current_equity))
    anchor = max(anchor_candidates) if anchor_candidates else None
    raw_value = float(raw_peak) if raw_peak is not None and float(raw_peak) > 0 else anchor
    if anchor is None or raw_value is None:
        return {
            "raw": raw_value,
            "sanitized": raw_value,
            "filtered": False,
            "anchor": anchor,
            "max_allowed": None,
        }
    if outlier_ratio <= 1.0:
        return {
            "raw": raw_value,
            "sanitized": raw_value,
            "filtered": False,
            "anchor": anchor,
            "max_allowed": None,
        }
    max_allowed = anchor * float(outlier_ratio)
    if raw_value > max_allowed:
        return {
            "raw": raw_value,
            "sanitized": anchor,
            "filtered": True,
            "anchor": anchor,
            "max_allowed": max_allowed,
        }
    return {
        "raw": raw_value,
        "sanitized": raw_value,
        "filtered": False,
        "anchor": anchor,
        "max_allowed": max_allowed,
    }


def _compute_drawdown_metrics(
    session,
    *,
    project_id: int,
    mode: str,
    trade_date: date,
    current_equity: float,
    current_day_peak: float,
    peak_all_outlier_ratio: float | None = None,
) -> dict[str, Any]:
    outlier_ratio = _coerce_peak_all_outlier_ratio(
        peak_all_outlier_ratio,
        default=float(_DEFAULT_GUARD_RISK_PARAMS["peak_all_outlier_ratio"]),
    )
    if current_equity <= 0:
        return {
            "dd_all": None,
            "dd_52w": None,
            "peak_all": None,
            "peak_52w": None,
            "peak_all_raw": None,
            "peak_all_outlier_filtered": False,
            "peak_all_outlier_ratio": outlier_ratio,
        }

    prior_window_rows = (
        session.query(
            TradeGuardState.last_equity,
            TradeGuardState.day_start_equity,
            TradeGuardState.valuation_source,
        )
        .filter(
            TradeGuardState.project_id == project_id,
            TradeGuardState.mode == mode,
            TradeGuardState.trade_date < trade_date,
            TradeGuardState.last_equity.isnot(None),
        )
        .order_by(TradeGuardState.trade_date.desc())
        .limit(251)
        .all()
    )
    window_values = []
    for row in reversed(prior_window_rows):
        raw_last = _coerce_optional_float(row[0])
        day_start = _coerce_optional_float(row[1])
        valuation_source = str(row[2] or "").strip().lower()
        if raw_last is None or raw_last <= 0:
            continue
        if valuation_source.startswith("local:") and day_start is not None and day_start > 0:
            max_allowed_local = float(day_start) * float(outlier_ratio)
            if raw_last > max_allowed_local:
                raw_last = float(day_start)
        if raw_last > 0:
            window_values.append(float(raw_last))
    window_values.append(float(current_equity))
    peak_52w = max(window_values) if window_values else float(current_equity)
    dd_52w = max(0.0, 1.0 - (float(current_equity) / peak_52w)) if peak_52w > 0 else None

    prior_peak_rows = (
        session.query(
            TradeGuardState.equity_peak,
            TradeGuardState.last_equity,
            TradeGuardState.day_start_equity,
            TradeGuardState.valuation_source,
        )
        .filter(
            TradeGuardState.project_id == project_id,
            TradeGuardState.mode == mode,
            TradeGuardState.trade_date < trade_date,
        )
        .all()
    )
    peak_all_candidates = [
        float(current_equity),
        float(current_day_peak) if current_day_peak > 0 else float(current_equity),
    ]
    for prior_peak_eq, prior_peak_last, prior_day_start, prior_source in prior_peak_rows:
        day_start = _coerce_optional_float(prior_day_start)
        valuation_source = str(prior_source or "").strip().lower()
        max_allowed_local = None
        if valuation_source.startswith("local:") and day_start is not None and day_start > 0:
            max_allowed_local = float(day_start) * float(outlier_ratio)
        for raw_value in (prior_peak_eq, prior_peak_last):
            value = _coerce_optional_float(raw_value)
            if value is None or value <= 0:
                continue
            if max_allowed_local is not None and value > max_allowed_local:
                value = float(day_start)
            if value > 0:
                peak_all_candidates.append(float(value))
    peak_all_raw = max(peak_all_candidates) if peak_all_candidates else float(current_equity)
    peak_all = peak_all_raw
    peak_all_outlier_filtered = False
    if peak_all_candidates and peak_52w > 0 and outlier_ratio > 1.0:
        max_allowed_peak = float(peak_52w) * float(outlier_ratio)
        bounded_candidates = [value for value in peak_all_candidates if value <= max_allowed_peak]
        if bounded_candidates:
            bounded_peak = max(bounded_candidates)
            if bounded_peak < peak_all_raw:
                peak_all_outlier_filtered = True
                peak_all = bounded_peak
    dd_all = max(0.0, 1.0 - (float(current_equity) / peak_all)) if peak_all > 0 else None

    return {
        "dd_all": dd_all,
        "dd_52w": dd_52w,
        "peak_all": peak_all,
        "peak_52w": peak_52w,
        "peak_all_raw": peak_all_raw,
        "peak_all_outlier_filtered": peak_all_outlier_filtered,
        "peak_all_outlier_ratio": outlier_ratio,
    }


def _load_ib_equity_snapshot(session, *, mode: str) -> dict[str, Any]:
    try:
        from app.services.ib_account import get_account_summary

        payload = get_account_summary(session, mode=mode, full=True, force_refresh=False)
    except Exception:
        return {}
    items = payload.get("items") if isinstance(payload.get("items"), dict) else {}
    net_liquidation = _coerce_optional_float(items.get("NetLiquidation"))
    unrealized_pnl = _coerce_optional_float(items.get("UnrealizedPnL"))
    realized_pnl = _coerce_optional_float(items.get("RealizedPnL"))
    by_currency_payload = items.get("__by_currency__") if isinstance(items.get("__by_currency__"), dict) else {}

    net_liq_by_currency = _normalize_currency_map(
        by_currency_payload.get("NetLiquidation") if isinstance(by_currency_payload, dict) else None
    )
    net_liq_by_currency = _merge_currency_maps(
        net_liq_by_currency,
        _normalize_currency_map(items.get("NetLiquidationByCurrency")),
    )

    unrealized_by_currency = _normalize_currency_map(
        by_currency_payload.get("UnrealizedPnL") if isinstance(by_currency_payload, dict) else None
    )
    unrealized_by_currency = _merge_currency_maps(
        unrealized_by_currency,
        _normalize_currency_map(items.get("UnrealizedPnLByCurrency")),
    )

    realized_by_currency = _normalize_currency_map(
        by_currency_payload.get("RealizedPnL") if isinstance(by_currency_payload, dict) else None
    )
    realized_by_currency = _merge_currency_maps(
        realized_by_currency,
        _normalize_currency_map(items.get("RealizedPnLByCurrency")),
    )

    pnl_total_by_currency: dict[str, float] = {}
    for currency in set(unrealized_by_currency.keys()) | set(realized_by_currency.keys()):
        pnl_total_by_currency[currency] = float(unrealized_by_currency.get(currency, 0.0)) + float(
            realized_by_currency.get(currency, 0.0)
        )

    if net_liquidation is None and net_liq_by_currency:
        net_liquidation = _sum_currency_map(net_liq_by_currency)
    if unrealized_pnl is None and unrealized_by_currency:
        unrealized_pnl = _sum_currency_map(unrealized_by_currency)
    if realized_pnl is None and realized_by_currency:
        realized_pnl = _sum_currency_map(realized_by_currency)

    return {
        "net_liquidation": net_liquidation,
        "unrealized_pnl": unrealized_pnl,
        "realized_pnl": realized_pnl,
        "net_liquidation_by_currency": net_liq_by_currency,
        "unrealized_pnl_by_currency": unrealized_by_currency,
        "realized_pnl_by_currency": realized_by_currency,
        "pnl_total_by_currency": pnl_total_by_currency,
        "stale": bool(payload.get("stale", True)),
        "source": payload.get("source") or "ib_account_summary",
    }


def load_guard_ib_snapshot(session, *, mode: str) -> dict[str, Any]:
    return _load_ib_equity_snapshot(session, mode=mode)


def _load_positions_via_broker(session, *, mode: str) -> dict[str, float] | None:
    try:
        bind = getattr(session, "bind", None)
        dialect_name = getattr(getattr(bind, "dialect", None), "name", "")
        if str(dialect_name or "").strip().lower() == "sqlite":
            return None
    except Exception:
        return None

    try:
        from app.services.ib_account import get_account_positions

        payload = get_account_positions(session, mode=mode, force_refresh=False)
    except Exception:
        return None

    if isinstance(payload, dict) and not bool(payload.get("stale", True)):
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        positions: dict[str, float] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").strip().upper()
            qty = _coerce_optional_float(item.get("quantity"))
            if not symbol or qty is None or abs(qty) <= 1e-9:
                continue
            positions[symbol] = float(qty)
        return positions
    return None


def _load_positions(session, *, project_id: int, mode: str) -> tuple[dict[str, float], str]:
    broker_positions = _load_positions_via_broker(session, mode=mode)
    if broker_positions is not None:
        return broker_positions, "broker_positions"

    positions = defaultdict(float)
    rows = (
        session.query(TradeOrder.symbol, TradeOrder.side, func.sum(TradeFill.fill_quantity))
        .join(TradeFill, TradeFill.order_id == TradeOrder.id)
        .join(TradeRun, TradeRun.id == TradeOrder.run_id)
        .filter(
            TradeRun.project_id == project_id,
            TradeRun.mode == mode,
        )
        .group_by(TradeOrder.symbol, TradeOrder.side)
        .all()
    )
    for symbol, side, qty in rows:
        if not symbol or qty is None:
            continue
        sign = 1.0 if (side or "").upper() == "BUY" else -1.0
        positions[str(symbol).upper()] += sign * float(qty)
    return {symbol: qty for symbol, qty in positions.items() if qty != 0}, "fills_history"


def _resolve_prices(
    session,
    symbols: list[str],
    *,
    stale_seconds: int,
    price_map: dict[str, float] | None,
) -> tuple[dict[str, float], str, int]:
    resolved: dict[str, float] = {}
    errors = 0
    source = "lean_bridge"
    now = datetime.now(timezone.utc)

    if not symbols:
        return resolved, "none", errors

    if price_map:
        for symbol, price in price_map.items():
            try:
                resolved[str(symbol).upper()] = float(price)
            except (TypeError, ValueError):
                continue
        if resolved:
            return resolved, source, errors

    quotes = read_quotes(_resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes.get("items"), list) else []
    stale = bool(quotes.get("stale", False))
    updated_at = quotes.get("updated_at") or quotes.get("refreshed_at")
    quotes_map = {
        str(item.get("symbol") or "").strip().upper(): item
        for item in items
        if isinstance(item, dict) and str(item.get("symbol") or "").strip()
    }
    for symbol in symbols:
        payload = quotes_map.get(symbol)
        if not isinstance(payload, dict):
            errors += 1
            continue
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        price = _pick_price(data if isinstance(data, dict) else None)
        ts_value = payload.get("timestamp") or (data.get("timestamp") if isinstance(data, dict) else None) or updated_at
        ts = _parse_timestamp(ts_value if isinstance(ts_value, str) else None)
        if price is None:
            errors += 1
            continue
        if stale and ts is None:
            errors += 1
            continue
        if ts and now - ts > timedelta(seconds=stale_seconds):
            errors += 1
            continue
        resolved[symbol] = price

    return resolved, source, errors


def evaluate_intraday_guard(
    session,
    *,
    project_id: int,
    mode: str,
    risk_params: dict[str, Any] | None = None,
    price_map: dict[str, float] | None = None,
    trade_date: date | None = None,
    ib_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = get_or_create_guard_state(session, project_id=project_id, mode=mode, trade_date=trade_date)
    settings_row = session.query(TradeSettings).order_by(TradeSettings.id.desc()).first()
    defaults = settings_row.risk_defaults if settings_row else {}
    risk_params = _normalize_guard_risk_params(_merge_risk_params(defaults, risk_params))

    stale_seconds = int(risk_params.get("valuation_stale_seconds") or 120)

    positions, positions_source = _load_positions(session, project_id=project_id, mode=mode)
    symbols = sorted(positions.keys())
    prices, valuation_source, market_errors = _resolve_prices(
        session,
        symbols,
        stale_seconds=stale_seconds,
        price_map=price_map,
    )

    if market_errors:
        state.market_data_errors = int(state.market_data_errors or 0) + market_errors

    cash_available = float(risk_params.get("cash_available") or 0.0)
    local_equity = cash_available
    for symbol, qty in positions.items():
        price = prices.get(symbol)
        if price is None:
            continue
        local_equity += qty * price

    equity_source = f"local:{valuation_source}"
    equity = local_equity
    cashflow_adjustment = 0.0
    if isinstance(ib_snapshot, dict):
        ib_snapshot_payload = dict(ib_snapshot)
    else:
        ib_snapshot_payload = _load_ib_equity_snapshot(session, mode=mode)
    ib_net_liq = _coerce_optional_float(ib_snapshot_payload.get("net_liquidation"))
    ib_unrealized = _coerce_optional_float(ib_snapshot_payload.get("unrealized_pnl"))
    ib_realized = _coerce_optional_float(ib_snapshot_payload.get("realized_pnl"))
    ib_pnl_total_by_currency = _normalize_currency_map(ib_snapshot_payload.get("pnl_total_by_currency"))
    ib_stale = bool(ib_snapshot_payload.get("stale", True))
    if ib_net_liq is not None and ib_net_liq > 0 and not ib_stale:
        equity_source = "ib_net_liquidation"
        equity = ib_net_liq
    cashflow_adjustment_mode = _normalize_cashflow_adjustment_mode(risk_params.get("cashflow_adjustment_mode"))
    manual_cashflow_adjustment = _coerce_optional_float(risk_params.get("cashflow_adjustment_manual"))
    rebase_equity_baseline = bool(_coerce_optional_bool(risk_params.get("rebase_equity_baseline")))

    now = datetime.utcnow()
    adjusted_equity = equity
    if cashflow_adjustment_mode == "manual" and manual_cashflow_adjustment is not None:
        cashflow_adjustment = manual_cashflow_adjustment
        adjusted_equity = equity - cashflow_adjustment
    elif cashflow_adjustment_mode == "off":
        cashflow_adjustment = 0.0
        adjusted_equity = equity
    elif equity_source == "ib_net_liquidation" and ib_unrealized is not None and ib_realized is not None:
        pnl_total = ib_unrealized + ib_realized
        mode_key = str(mode or "paper").strip().lower() or "paper"
        baseline_key = (int(project_id), mode_key, state.trade_date.isoformat())
        baseline_pnl, baseline_pnl_by_currency = _get_or_init_ib_baseline_pnl_entry(
            baseline_key,
            pnl_total=pnl_total,
            pnl_by_currency=ib_pnl_total_by_currency,
        )
        baseline_equity = state.day_start_equity if state.day_start_equity is not None else equity
        market_pnl = pnl_total - baseline_pnl
        if ib_pnl_total_by_currency and baseline_pnl_by_currency:
            market_pnl = _compute_market_pnl_from_currency_maps(ib_pnl_total_by_currency, baseline_pnl_by_currency)
        cashflow_adjustment = equity - (baseline_equity + market_pnl)
        adjusted_equity = equity - cashflow_adjustment

    required_symbols = len(symbols)
    priced_symbols = sum(1 for symbol in symbols if symbol in prices)
    price_coverage = 1.0 if required_symbols <= 0 else float(priced_symbols) / float(required_symbols)
    min_price_coverage = _coerce_optional_float(risk_params.get("min_price_coverage"))
    if min_price_coverage is None or min_price_coverage < 0:
        min_price_coverage = 0.0

    valuation_quality_details: list[dict[str, Any]] = []
    had_positive_equity_baseline = bool((state.day_start_equity or 0.0) > 0 or (state.last_equity or 0.0) > 0)
    if adjusted_equity <= 0 and (had_positive_equity_baseline or required_symbols > 0):
        valuation_quality_details.append(
            {
                "reason": "equity_non_positive",
                "value": adjusted_equity,
                "threshold": 0.0,
            }
        )

    using_local_valuation = str(equity_source).startswith("local:")
    if using_local_valuation and required_symbols > 0:
        if positions_source != "broker_positions" and had_positive_equity_baseline:
            valuation_quality_details.append(
                {
                    "reason": "positions_source_untrusted",
                    "value": positions_source,
                    "threshold": "broker_positions",
                }
            )
        if priced_symbols <= 0:
            valuation_quality_details.append(
                {
                    "reason": "local_prices_missing",
                    "value": priced_symbols,
                    "threshold": 1,
                }
            )
        elif min_price_coverage > 0 and price_coverage < min_price_coverage:
            valuation_quality_details.append(
                {
                    "reason": "price_coverage_low",
                    "value": price_coverage,
                    "threshold": min_price_coverage,
                }
            )
        if market_errors >= max(1, required_symbols) and priced_symbols <= 0:
            valuation_quality_details.append(
                {
                    "reason": "market_data_errors_excessive",
                    "value": market_errors,
                    "threshold": required_symbols,
                }
            )

    if valuation_quality_details:
        thresholds_payload = {
            "max_daily_loss": float(risk_params.get("max_daily_loss")),
            "max_intraday_drawdown": float(risk_params.get("max_intraday_drawdown")),
            "max_drawdown": _coerce_positive_ratio(risk_params.get("max_drawdown")),
            "max_drawdown_52w": _coerce_positive_ratio(risk_params.get("max_drawdown_52w")),
            "drawdown_recovery_ratio": _coerce_recovery_ratio(risk_params.get("drawdown_recovery_ratio"), default=0.9),
            "max_order_failures": _coerce_optional_int(risk_params.get("max_order_failures")),
            "max_market_data_errors": _coerce_optional_int(risk_params.get("max_market_data_errors")),
            "max_risk_triggers": _coerce_optional_int(risk_params.get("max_risk_triggers")),
            "cooldown_seconds": int(risk_params.get("cooldown_seconds") or 0),
            "min_price_coverage": min_price_coverage,
        }
        dd_lock_state = _is_drawdown_lock_active(state)
        metrics_payload = {
            "day_start_equity": state.day_start_equity,
            "equity_peak": state.equity_peak,
            "daily_loss": None,
            "drawdown": None,
            "intraday_drawdown": None,
            "equity_raw": equity,
            "equity_adjusted": adjusted_equity,
            "equity_source": equity_source,
            "cashflow_adjustment_mode": cashflow_adjustment_mode,
            "baseline_rebased": False,
            "cashflow_adjustment": cashflow_adjustment,
            "pnl_total_by_currency": ib_pnl_total_by_currency if ib_pnl_total_by_currency else None,
            "dd_all": None,
            "dd_52w": None,
            "peak_all": None,
            "peak_52w": None,
            "dd_lock_state": dd_lock_state,
            "market_data_errors": int(state.market_data_errors or 0),
            "order_failures": int(state.order_failures or 0),
            "risk_triggers": int(state.risk_triggers or 0),
            "valuation_quality": "degraded",
            "required_symbols": required_symbols,
            "priced_symbols": priced_symbols,
            "price_coverage": price_coverage,
            "ib_snapshot_stale": ib_stale,
        }
        quality_reason = {
            "reasons": ["valuation_unreliable"],
            "details": valuation_quality_details,
            "triggered_at": now.isoformat(timespec="seconds"),
            "valuation_source": equity_source,
            "thresholds": thresholds_payload,
            "metrics": metrics_payload,
        }
        state.last_valuation_ts = now
        state.valuation_source = equity_source
        if adjusted_equity > 0:
            state.last_equity = adjusted_equity
        state.updated_at = now
        session.commit()
        session.refresh(state)
        return {
            "status": "degraded",
            "reason": quality_reason,
            "valuation_source": state.valuation_source,
            "equity": adjusted_equity,
            "equity_source": metrics_payload.get("equity_source"),
            "cashflow_adjustment": metrics_payload.get("cashflow_adjustment"),
            "dd_all": metrics_payload.get("dd_all"),
            "dd_52w": metrics_payload.get("dd_52w"),
            "dd_lock_state": dd_lock_state,
            "thresholds": thresholds_payload,
            "metrics": metrics_payload,
            "trigger_details": valuation_quality_details,
        }

    baseline_rebased = False
    if rebase_equity_baseline and adjusted_equity > 0:
        state.day_start_equity = adjusted_equity
        state.equity_peak = adjusted_equity
        baseline_rebased = True

    if state.day_start_equity is None and adjusted_equity > 0:
        state.day_start_equity = adjusted_equity
    if state.equity_peak is None and adjusted_equity > 0:
        state.equity_peak = adjusted_equity
    if adjusted_equity > 0 and state.equity_peak is not None:
        state.equity_peak = max(state.equity_peak, adjusted_equity)

    state.last_equity = adjusted_equity if adjusted_equity > 0 else state.last_equity
    state.last_valuation_ts = now
    state.valuation_source = equity_source

    day_start = state.day_start_equity or 0.0
    daily_loss: float | None = None
    max_daily_loss = float(risk_params.get("max_daily_loss"))
    max_intraday_drawdown = float(risk_params.get("max_intraday_drawdown"))
    if day_start > 0:
        daily_loss = (adjusted_equity - day_start) / day_start

    raw_intraday_peak = _coerce_optional_float(state.equity_peak)

    drawdown_metrics = _compute_drawdown_metrics(
        session,
        project_id=project_id,
        mode=mode,
        trade_date=state.trade_date,
        current_equity=adjusted_equity,
        current_day_peak=raw_intraday_peak if raw_intraday_peak is not None and raw_intraday_peak > 0 else adjusted_equity,
        peak_all_outlier_ratio=risk_params.get("peak_all_outlier_ratio"),
    )
    dd_all = _coerce_optional_float(drawdown_metrics.get("dd_all"))
    dd_52w = _coerce_optional_float(drawdown_metrics.get("dd_52w"))
    peak_all = _coerce_optional_float(drawdown_metrics.get("peak_all"))
    peak_52w = _coerce_optional_float(drawdown_metrics.get("peak_52w"))
    peak_all_raw = _coerce_optional_float(drawdown_metrics.get("peak_all_raw"))
    peak_all_outlier_filtered = bool(drawdown_metrics.get("peak_all_outlier_filtered"))
    peak_all_outlier_ratio = _coerce_peak_all_outlier_ratio(risk_params.get("peak_all_outlier_ratio"))
    intraday_peak_payload = _sanitize_intraday_peak(
        raw_intraday_peak,
        day_start_equity=state.day_start_equity,
        current_equity=adjusted_equity,
        peak_52w=peak_52w,
        outlier_ratio=peak_all_outlier_ratio,
    )
    intraday_peak_raw = _coerce_optional_float(intraday_peak_payload.get("raw"))
    peak_intraday = _coerce_optional_float(intraday_peak_payload.get("sanitized")) or 0.0
    intraday_peak_outlier_filtered = bool(intraday_peak_payload.get("filtered"))
    intraday_peak_anchor = _coerce_optional_float(intraday_peak_payload.get("anchor"))
    intraday_peak_max_allowed = _coerce_optional_float(intraday_peak_payload.get("max_allowed"))
    if intraday_peak_outlier_filtered and peak_intraday > 0:
        state.equity_peak = peak_intraday

    intraday_drawdown: float | None = None
    if peak_intraday > 0:
        intraday_drawdown = (adjusted_equity - peak_intraday) / peak_intraday

    max_drawdown = _coerce_positive_ratio(risk_params.get("max_drawdown"))
    max_drawdown_52w = _coerce_positive_ratio(risk_params.get("max_drawdown_52w"))
    drawdown_recovery_ratio = _coerce_recovery_ratio(risk_params.get("drawdown_recovery_ratio"), default=0.9)

    reasons: list[str] = []
    trigger_details: list[dict[str, Any]] = []
    if daily_loss is not None and daily_loss <= max_daily_loss:
        reasons.append("max_daily_loss")
        trigger_details.append(
            {
                "reason": "max_daily_loss",
                "value": daily_loss,
                "threshold": max_daily_loss,
            }
        )
    if intraday_drawdown is not None and intraday_drawdown <= -abs(max_intraday_drawdown):
        reasons.append("max_intraday_drawdown")
        trigger_details.append(
            {
                "reason": "max_intraday_drawdown",
                "value": intraday_drawdown,
                "threshold": -abs(max_intraday_drawdown),
            }
        )
    if dd_all is not None and max_drawdown is not None and dd_all >= max_drawdown:
        reasons.append("max_drawdown")
        trigger_details.append(
            {
                "reason": "max_drawdown",
                "value": dd_all,
                "threshold": max_drawdown,
            }
        )
    if dd_52w is not None and max_drawdown_52w is not None and dd_52w >= max_drawdown_52w:
        reasons.append("max_drawdown_52w")
        trigger_details.append(
            {
                "reason": "max_drawdown_52w",
                "value": dd_52w,
                "threshold": max_drawdown_52w,
            }
        )

    max_order_failures = _coerce_optional_int(risk_params.get("max_order_failures"))
    if max_order_failures is not None and (state.order_failures or 0) >= max_order_failures:
        reasons.append("max_order_failures")
        trigger_details.append(
            {
                "reason": "max_order_failures",
                "value": int(state.order_failures or 0),
                "threshold": int(max_order_failures),
            }
        )

    max_market_errors = _coerce_optional_int(risk_params.get("max_market_data_errors"))
    if max_market_errors is not None and (state.market_data_errors or 0) >= max_market_errors:
        reasons.append("max_market_data_errors")
        trigger_details.append(
            {
                "reason": "max_market_data_errors",
                "value": int(state.market_data_errors or 0),
                "threshold": int(max_market_errors),
            }
        )

    max_risk_triggers = _coerce_optional_int(risk_params.get("max_risk_triggers"))
    if max_risk_triggers is not None and (state.risk_triggers or 0) >= max_risk_triggers:
        reasons.append("max_risk_triggers")
        trigger_details.append(
            {
                "reason": "max_risk_triggers",
                "value": int(state.risk_triggers or 0),
                "threshold": int(max_risk_triggers),
            }
        )

    drawdown_lock_active = _is_drawdown_lock_active(state)
    if drawdown_lock_active:
        unlock_all = True
        unlock_52w = True
        if max_drawdown is not None and dd_all is not None:
            unlock_all = dd_all <= max_drawdown * drawdown_recovery_ratio
        if max_drawdown_52w is not None and dd_52w is not None:
            unlock_52w = dd_52w <= max_drawdown_52w * drawdown_recovery_ratio
        if unlock_all and unlock_52w:
            state.status = "active"
            state.cooldown_until = None
            state.halt_reason = {
                "unlock_reason": "drawdown_recovered",
                "unlocked_at": now.isoformat(timespec="seconds"),
                "metrics": {"dd_all": dd_all, "dd_52w": dd_52w},
                "thresholds": {
                    "max_drawdown": max_drawdown,
                    "max_drawdown_52w": max_drawdown_52w,
                    "drawdown_recovery_ratio": drawdown_recovery_ratio,
                },
            }
            drawdown_lock_active = False
        else:
            reasons.append("drawdown_lock")
            trigger_details.append(
                {
                    "reason": "drawdown_lock",
                    "value": {"dd_all": dd_all, "dd_52w": dd_52w},
                    "threshold": {
                        "max_drawdown_unlock": (
                            max_drawdown * drawdown_recovery_ratio if max_drawdown is not None else None
                        ),
                        "max_drawdown_52w_unlock": (
                            max_drawdown_52w * drawdown_recovery_ratio
                            if max_drawdown_52w is not None
                            else None
                        ),
                    },
                }
            )

    thresholds_payload = {
        "max_daily_loss": max_daily_loss,
        "max_intraday_drawdown": max_intraday_drawdown,
        "max_drawdown": max_drawdown,
        "max_drawdown_52w": max_drawdown_52w,
        "peak_all_outlier_ratio": peak_all_outlier_ratio,
        "drawdown_recovery_ratio": drawdown_recovery_ratio,
        "max_order_failures": max_order_failures,
        "max_market_data_errors": max_market_errors,
        "max_risk_triggers": max_risk_triggers,
        "cooldown_seconds": int(risk_params.get("cooldown_seconds") or 0),
    }
    metrics_payload = {
        "day_start_equity": day_start if day_start > 0 else None,
        "equity_peak": peak_intraday if peak_intraday > 0 else None,
        "daily_loss": daily_loss,
        "drawdown": intraday_drawdown,
        "intraday_drawdown": intraday_drawdown,
        "equity_raw": equity,
        "equity_adjusted": adjusted_equity,
        "equity_source": equity_source,
        "cashflow_adjustment_mode": cashflow_adjustment_mode,
        "baseline_rebased": baseline_rebased,
        "cashflow_adjustment": cashflow_adjustment,
        "pnl_total_by_currency": ib_pnl_total_by_currency if ib_pnl_total_by_currency else None,
        "dd_all": dd_all,
        "dd_52w": dd_52w,
        "peak_all": peak_all,
        "peak_all_raw": peak_all_raw,
        "peak_all_outlier_filtered": peak_all_outlier_filtered,
        "peak_52w": peak_52w,
        "intraday_peak_raw": intraday_peak_raw,
        "intraday_peak_sanitized": peak_intraday if peak_intraday > 0 else None,
        "intraday_peak_outlier_filtered": intraday_peak_outlier_filtered,
        "intraday_peak_anchor": intraday_peak_anchor,
        "intraday_peak_max_allowed": intraday_peak_max_allowed,
        "dd_lock_state": False,
        "market_data_errors": int(state.market_data_errors or 0),
        "order_failures": int(state.order_failures or 0),
        "risk_triggers": int(state.risk_triggers or 0),
        "valuation_quality": "ok",
        "required_symbols": required_symbols,
        "priced_symbols": priced_symbols,
        "price_coverage": price_coverage,
        "ib_snapshot_stale": ib_stale,
    }

    prior_reason_list = _extract_reason_list(state.halt_reason)
    only_prior_intraday_halt = bool(prior_reason_list) and set(prior_reason_list) == {"max_intraday_drawdown"}
    if not reasons and intraday_peak_outlier_filtered and only_prior_intraday_halt:
        _try_unlock_non_drawdown_halt(
            state,
            now=now,
            unlock_reason="intraday_peak_outlier_filtered",
            metrics=metrics_payload,
            thresholds=thresholds_payload,
            ignore_cooldown=True,
        )
    elif not reasons:
        _try_unlock_non_drawdown_halt(
            state,
            now=now,
            unlock_reason="cooldown_elapsed",
            metrics=metrics_payload,
            thresholds=thresholds_payload,
        )

    if reasons:
        if state.status != "halted":
            state.status = "halted"
            state.risk_triggers = int(state.risk_triggers or 0) + 1
            metrics_payload["risk_triggers"] = int(state.risk_triggers or 0)
            cooldown_seconds = int(thresholds_payload.get("cooldown_seconds") or 0)
            if cooldown_seconds > 0:
                state.cooldown_until = now + timedelta(seconds=cooldown_seconds)
        state.halt_reason = {
            "reasons": reasons,
            "details": trigger_details,
            "triggered_at": now.isoformat(timespec="seconds"),
            "valuation_source": equity_source,
            "thresholds": thresholds_payload,
            "metrics": metrics_payload,
        }

    dd_lock_state = str(state.status or "").strip().lower() == "halted" and (
        drawdown_lock_active or any(reason in _DRAWDOWN_LOCK_REASONS for reason in reasons)
    )
    metrics_payload["dd_lock_state"] = dd_lock_state

    state.updated_at = now
    session.commit()
    session.refresh(state)

    return {
        "status": state.status,
        "reason": state.halt_reason,
        "valuation_source": state.valuation_source,
        "equity": state.last_equity,
        "equity_source": metrics_payload.get("equity_source"),
        "cashflow_adjustment": metrics_payload.get("cashflow_adjustment"),
        "dd_all": metrics_payload.get("dd_all"),
        "dd_52w": metrics_payload.get("dd_52w"),
        "dd_lock_state": dd_lock_state,
        "thresholds": thresholds_payload,
        "metrics": metrics_payload,
        "trigger_details": trigger_details,
    }
