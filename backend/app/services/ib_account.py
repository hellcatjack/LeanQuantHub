from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from app.services.ib_market import _ib_data_root
from app.services.ib_settings import get_or_create_ib_settings

CORE_TAGS = {
    "NetLiquidation",
    "TotalCashValue",
    "AvailableFunds",
    "BuyingPower",
    "GrossPositionValue",
    "EquityWithLoanValue",
    "UnrealizedPnL",
    "RealizedPnL",
    "InitMarginReq",
    "MaintMarginReq",
    "AccruedCash",
    "CashBalance",
}

SUMMARY_TTL_SECONDS = 60


def _parse_value(value: str) -> float | str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return text


def _filter_summary(raw: dict[str, str], full: bool) -> dict[str, object]:
    items: dict[str, object] = {}
    for key, value in raw.items():
        if full or key in CORE_TAGS:
            items[key] = _parse_value(value)
    return items


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _is_stale(refreshed_at: str | None) -> bool:
    ts = _parse_timestamp(refreshed_at)
    if ts is None:
        return True
    age = (datetime.utcnow() - ts).total_seconds()
    return age >= SUMMARY_TTL_SECONDS


def _summary_cache_path(mode: str) -> Path:
    root = _ib_data_root() / "account"
    root.mkdir(parents=True, exist_ok=True)
    safe_mode = mode or "paper"
    return root / f"summary_{safe_mode}.json"


def read_cached_summary(cache_path: Path) -> dict[str, Any] | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def write_cached_summary(cache_path: Path, raw: dict[str, str], refreshed_at: datetime | None) -> None:
    payload = {
        "raw": raw,
        "refreshed_at": refreshed_at.isoformat() if refreshed_at else None,
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_summary_payload(raw: dict[str, str], refreshed_at: str | None, source: str, stale: bool, full: bool) -> dict[str, object]:
    return {
        "items": _filter_summary(raw, full=full),
        "refreshed_at": refreshed_at,
        "source": source,
        "stale": stale,
        "full": full,
    }


def _fetch_account_summary(session, mode: str) -> dict[str, str]:
    return {}


def get_account_summary(session, *, mode: str, full: bool, force_refresh: bool = False) -> dict[str, object]:
    cache_path = _summary_cache_path(mode)
    cached = read_cached_summary(cache_path)
    if cached and not force_refresh:
        raw = cached.get("raw") if isinstance(cached.get("raw"), dict) else {}
        refreshed_at = cached.get("refreshed_at")
        stale = _is_stale(refreshed_at)
        return _build_summary_payload(raw, refreshed_at, "cache", stale, full)
    raw = _fetch_account_summary(session, mode)
    if raw:
        refreshed_at = datetime.utcnow()
        write_cached_summary(cache_path, raw, refreshed_at)
        return _build_summary_payload(raw, refreshed_at.isoformat(), "refresh", False, full)
    if cached:
        raw = cached.get("raw") if isinstance(cached.get("raw"), dict) else {}
        refreshed_at = cached.get("refreshed_at")
        return _build_summary_payload(raw, refreshed_at, "cache", True, full)
    return {
        "items": {},
        "refreshed_at": None,
        "source": "cache",
        "stale": True,
        "full": full,
    }


def fetch_account_summary(session) -> dict[str, float | str | None]:
    settings_row = get_or_create_ib_settings(session)
    mode = settings_row.mode or "paper"
    summary = get_account_summary(session, mode=mode, full=False, force_refresh=False)
    items = summary.get("items") if isinstance(summary.get("items"), dict) else {}
    cash_available = items.get("AvailableFunds") or items.get("CashBalance") or items.get("TotalCashValue")
    if isinstance(cash_available, str):
        try:
            cash_available = float(cash_available)
        except ValueError:
            pass
    output: dict[str, float | str | None] = dict(items)
    output["cash_available"] = cash_available
    return output
