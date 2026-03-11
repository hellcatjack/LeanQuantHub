from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.ib_market import fetch_historical_bars


@dataclass(frozen=True)
class ChartHistoryRequest:
    symbol: str
    interval: str
    ib_bar_size: str
    ib_duration: str
    range_label: str
    allow_local_fallback: bool
    local_granularity: str | None = None


_INTERVAL_CONFIG: dict[str, dict[str, Any]] = {
    "1m": {
        "ib_bar_size": "1 min",
        "ib_duration": "1 D",
        "range_label": "1D",
        "allow_local_fallback": False,
    },
    "5m": {
        "ib_bar_size": "5 mins",
        "ib_duration": "5 D",
        "range_label": "5D",
        "allow_local_fallback": False,
    },
    "15m": {
        "ib_bar_size": "15 mins",
        "ib_duration": "10 D",
        "range_label": "10D",
        "allow_local_fallback": False,
    },
    "1h": {
        "ib_bar_size": "1 hour",
        "ib_duration": "30 D",
        "range_label": "30D",
        "allow_local_fallback": False,
    },
    "1D": {
        "ib_bar_size": "1 day",
        "ib_duration": "6 M",
        "range_label": "6M",
        "allow_local_fallback": True,
        "local_granularity": "day",
    },
    "1W": {
        "ib_bar_size": "1 week",
        "ib_duration": "2 Y",
        "range_label": "2Y",
        "allow_local_fallback": True,
        "local_granularity": "week",
    },
    "1M": {
        "ib_bar_size": "1 month",
        "ib_duration": "5 Y",
        "range_label": "5Y",
        "allow_local_fallback": True,
        "local_granularity": "month",
    },
}


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def _normalize_symbol(symbol: str | None) -> str:
    return str(symbol or "").strip().upper()


def _normalize_interval(interval: str | None) -> str:
    value = str(interval or "").strip()
    if not value:
        return "1D"
    lowered = value.lower()
    if lowered in {"1m", "5m", "15m", "1h"}:
        return lowered
    uppered = value.upper()
    if uppered in {"1D", "1W", "1M"}:
        return uppered
    return value


def build_chart_request(*, symbol: str, interval: str) -> ChartHistoryRequest:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_interval = _normalize_interval(interval)
    config = _INTERVAL_CONFIG.get(normalized_interval)
    if not normalized_symbol:
        raise ValueError("symbol_required")
    if not isinstance(config, dict):
        raise ValueError("unsupported_interval")
    return ChartHistoryRequest(
        symbol=normalized_symbol,
        interval=normalized_interval,
        ib_bar_size=str(config["ib_bar_size"]),
        ib_duration=str(config["ib_duration"]),
        range_label=str(config["range_label"]),
        allow_local_fallback=bool(config["allow_local_fallback"]),
        local_granularity=str(config.get("local_granularity") or "") or None,
    )


def _normalize_symbol_for_filename(symbol: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in symbol.upper()).strip("_")


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


def _parse_date(value: str | None) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _to_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _parse_daily_row(row: dict[str, Any]) -> dict[str, Any] | None:
    row_date = _parse_date(row.get("date"))
    open_ = _to_float(row.get("open"))
    high = _to_float(row.get("high"))
    low = _to_float(row.get("low"))
    close = _to_float(row.get("close"))
    if row_date is None or None in {open_, high, low, close}:
        return None
    volume = _to_float(row.get("volume"))
    return {
        "date": row_date,
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume) if volume is not None else None,
    }


def _read_local_daily_rows(symbol: str) -> list[dict[str, Any]]:
    root = _resolve_data_root() / "curated_adjusted"
    path = _find_latest_price_file(root, symbol)
    if path is None:
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                parsed = _parse_daily_row(row)
                if parsed is not None:
                    rows.append(parsed)
    except OSError:
        return []
    rows.sort(key=lambda item: item["date"])
    return rows


def _group_key(row_date: date, granularity: str) -> tuple[int, int]:
    if granularity == "week":
        iso_year, iso_week, _ = row_date.isocalendar()
        return (iso_year, iso_week)
    return (row_date.year, row_date.month)


def aggregate_daily_bars(rows: list[dict[str, Any]], *, granularity: str) -> list[dict[str, Any]]:
    if granularity not in {"week", "month"}:
        return list(rows)
    aggregated: list[dict[str, Any]] = []
    current_key: tuple[int, int] | None = None
    current: dict[str, Any] | None = None
    for row in rows:
        row_date = row["date"]
        key = _group_key(row_date, granularity)
        if key != current_key or current is None:
            if current is not None:
                aggregated.append(current)
            current_key = key
            current = {
                "date": row_date,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"] or 0.0,
            }
            continue
        current["date"] = row_date
        current["high"] = max(float(current["high"]), float(row["high"]))
        current["low"] = min(float(current["low"]), float(row["low"]))
        current["close"] = row["close"]
        current["volume"] = float(current["volume"] or 0.0) + float(row["volume"] or 0.0)
    if current is not None:
        aggregated.append(current)
    return aggregated


def _bar_time(row_date: date) -> int:
    return int(datetime(row_date.year, row_date.month, row_date.day, tzinfo=timezone.utc).timestamp())


def _normalize_local_bars(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    for row in rows:
        bars.append(
            {
                "time": _bar_time(row["date"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]) if row.get("volume") is not None else None,
            }
        )
    return bars


def load_local_adjusted_bars(symbol: str, interval: str) -> list[dict[str, Any]]:
    request = build_chart_request(symbol=symbol, interval=interval)
    rows = _read_local_daily_rows(request.symbol)
    if request.local_granularity == "week":
        rows = aggregate_daily_bars(rows, granularity="week")
    elif request.local_granularity == "month":
        rows = aggregate_daily_bars(rows, granularity="month")
    return _normalize_local_bars(rows)


def _normalize_ib_bars(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    bars: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        time_value = item.get("time")
        open_ = _to_float(item.get("open"))
        high = _to_float(item.get("high"))
        low = _to_float(item.get("low"))
        close = _to_float(item.get("close"))
        if None in {open_, high, low, close}:
            continue
        if isinstance(time_value, datetime):
            timestamp = int(time_value.timestamp())
        elif isinstance(time_value, (int, float)):
            timestamp = int(time_value)
        else:
            parsed = None
            text = str(time_value or "").strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                parsed = None
            if parsed is None:
                continue
            timestamp = int(parsed.timestamp())
        bars.append(
            {
                "time": timestamp,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": _to_float(item.get("volume")),
            }
        )
    return bars


def normalize_chart_response(
    *,
    symbol: str,
    interval: str,
    source: str,
    bars: list[dict[str, Any]] | None = None,
    fallback_used: bool = False,
    stale: bool = False,
    range_label: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_interval = _normalize_interval(interval)
    chart_bars = list(bars or [])
    last_bar_at = None
    if chart_bars:
        last_bar_at = datetime.fromtimestamp(int(chart_bars[-1]["time"]), tz=timezone.utc).isoformat()
    return {
        "symbol": normalized_symbol,
        "interval": normalized_interval,
        "source": source,
        "fallback_used": bool(fallback_used),
        "stale": bool(stale),
        "bars": chart_bars,
        "markers": [],
        "meta": {
            "price_precision": 2,
            "currency": "USD",
            "range_label": range_label,
            "last_bar_at": last_bar_at,
        },
        "error": error,
    }


def load_chart_history(
    *,
    symbol: str,
    interval: str,
    mode: str = "paper",
    use_rth: bool = True,
    session=None,
) -> dict[str, Any]:
    request = build_chart_request(symbol=symbol, interval=interval)
    ib_error = "ib_history_unavailable"
    try:
        ib_payload = fetch_historical_bars(
            session,
            symbol=request.symbol,
            duration=request.ib_duration,
            bar_size=request.ib_bar_size,
            end_datetime=None,
            use_rth=bool(use_rth),
            store=False,
        )
    except Exception:
        ib_payload = {"symbol": request.symbol, "bars": 0, "error": ib_error}
    bars = _normalize_ib_bars(ib_payload if isinstance(ib_payload, dict) else {})
    if bars:
        stale = bool(ib_payload.get("stale", False)) if isinstance(ib_payload, dict) else False
        return normalize_chart_response(
            symbol=request.symbol,
            interval=request.interval,
            source="ib",
            bars=bars,
            fallback_used=False,
            stale=stale,
            range_label=request.range_label,
            error=None,
        )
    if not request.allow_local_fallback:
        return normalize_chart_response(
            symbol=request.symbol,
            interval=request.interval,
            source="unavailable",
            bars=[],
            fallback_used=False,
            stale=False,
            range_label=request.range_label,
            error=ib_error,
        )
    local_bars = load_local_adjusted_bars(request.symbol, request.interval)
    if local_bars:
        return normalize_chart_response(
            symbol=request.symbol,
            interval=request.interval,
            source="local",
            bars=local_bars,
            fallback_used=True,
            stale=False,
            range_label=request.range_label,
            error=None,
        )
    return normalize_chart_response(
        symbol=request.symbol,
        interval=request.interval,
        source="unavailable",
        bars=[],
        fallback_used=False,
        stale=False,
        range_label=request.range_label,
        error="local_history_missing",
    )
