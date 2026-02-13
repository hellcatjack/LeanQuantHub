from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any
import csv
import json
import os
import signal
import re
from zoneinfo import ZoneInfo

from sqlalchemy import func

from app.core.config import settings
from app.db import SessionLocal
from app.models import DecisionSnapshot, TradeFill, TradeOrder, TradeRun, TradeSettings
from pathlib import Path

from app.services.job_lock import JobLock
from app.services.trade_guard import (
    get_or_create_guard_state,
    record_guard_event,
)
from app.services.trade_order_builder import build_intent_orders, build_orders, build_rebalance_orders
from app.services.trade_orders import create_trade_order, force_update_trade_order_status, update_trade_order_status
from app.services.trade_order_types import is_limit_like, normalize_order_type, validate_order_type
from app.services.trade_risk_engine import evaluate_orders
from app.services.trade_alerts import notify_trade_alert
from app.services.ib_account import fetch_account_summary
from app.services.trade_order_intent import write_order_intent, ensure_order_intent_ids
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import (
    parse_bridge_timestamp,
    read_bridge_status,
    read_open_orders,
    read_positions,
    read_quotes,
)
from app.services.lean_bridge_commands import write_submit_order_command
from app.services.lean_execution import (
    build_execution_config,
    ingest_execution_events,
    launch_execution_async,
)
from app.services.lean_execution_params import write_execution_params
from app.services.audit_log import record_audit
from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders
from app.services.trade_run_progress import is_market_open, is_trade_run_stalled, update_trade_run_progress


ARTIFACT_ROOT = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")


@dataclass
class TradeExecutionResult:
    run_id: int
    status: str
    filled: int
    cancelled: int
    rejected: int
    skipped: int
    message: str | None
    dry_run: bool


def _pick_price(snapshot: dict[str, Any] | None) -> float | None:
    if not snapshot:
        return None
    for key in ("last", "close", "bid", "ask"):
        value = snapshot.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _pick_quote_limit_price(
    snapshot: dict[str, Any] | None,
    *,
    side: str,
    prefer_mid: bool = False,
) -> float | None:
    if not snapshot:
        return None
    last = snapshot.get("last")
    bid = snapshot.get("bid")
    ask = snapshot.get("ask")
    try:
        last_value = float(last) if last is not None else None
    except (TypeError, ValueError):
        last_value = None
    try:
        bid_value = float(bid) if bid is not None else None
    except (TypeError, ValueError):
        bid_value = None
    try:
        ask_value = float(ask) if ask is not None else None
    except (TypeError, ValueError):
        ask_value = None

    if prefer_mid and bid_value is not None and ask_value is not None and bid_value > 0 and ask_value > 0:
        return (bid_value + ask_value) / 2.0

    if last_value is not None and last_value > 0:
        return last_value

    if (not prefer_mid) and bid_value is not None and ask_value is not None and bid_value > 0 and ask_value > 0:
        return (bid_value + ask_value) / 2.0

    normalized_side = str(side or "").strip().upper()
    if normalized_side == "BUY":
        if ask_value is not None and ask_value > 0:
            return ask_value
        if bid_value is not None and bid_value > 0:
            return bid_value
    if normalized_side == "SELL":
        if bid_value is not None and bid_value > 0:
            return bid_value
        if ask_value is not None and ask_value > 0:
            return ask_value
    if bid_value is not None and bid_value > 0:
        return bid_value
    if ask_value is not None and ask_value > 0:
        return ask_value
    return None


def _infer_auto_session(now: datetime) -> tuple[str, bool]:
    """Infer execution session for auto (snapshot-based) runs.

    We use settings.market_timezone/open/close to decide "rth" vs extended sessions.
    """

    current = now
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    try:
        zone = ZoneInfo(settings.market_timezone)
    except Exception:
        zone = timezone.utc
    local = current.astimezone(zone)
    if is_market_open(current):
        return "rth", False
    # Extended hours split for better UI/logging. Defaults follow US equities convention.
    # pre: 04:00 - open, post: close - 20:00, night: others.
    open_time = time(9, 30)
    close_time = time(16, 0)
    pre_start = time(4, 0)
    post_end = time(20, 0)
    now_time = local.time()
    if local.weekday() >= 5:
        return "night", True
    if pre_start <= now_time < open_time:
        return "pre", True
    if close_time < now_time <= post_end:
        return "post", True
    return "night", True


def _build_limit_price_map(
    symbols: list[str],
    *,
    side_map: dict[str, str],
    order_type: str,
    fallback_prices: dict[str, float] | None = None,
) -> dict[str, float]:
    symbol_set = {symbol for symbol in symbols if symbol}
    quotes = read_quotes(_resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes.get("items"), list) else []
    quote_map: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol or symbol not in symbol_set:
            continue
        payload = item.get("data") if isinstance(item.get("data"), dict) else item
        quote_map[symbol] = payload if isinstance(payload, dict) else {}

    prefer_mid = normalize_order_type(order_type) == "PEG_MID"
    out: dict[str, float] = {}
    for symbol in sorted(symbol_set):
        snapshot = quote_map.get(symbol)
        side = side_map.get(symbol, "")
        picked = _pick_quote_limit_price(snapshot, side=side, prefer_mid=prefer_mid)
        if picked is not None and picked > 0:
            out[symbol] = float(picked)

    if fallback_prices:
        for symbol, price in fallback_prices.items():
            if symbol in symbol_set and symbol not in out and price is not None and float(price) > 0:
                out[symbol] = float(price)

    missing = sorted(symbol_set - set(out.keys()))
    if missing:
        out.update(_load_fallback_prices(missing))
    return out


def _resolve_bridge_root() -> Path:
    return resolve_bridge_root()


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def _bridge_connection_ok() -> bool:
    status = read_bridge_status(_resolve_bridge_root())
    state = str(status.get("status") or "").lower()
    if status.get("stale") is True:
        return False
    # "degraded" still has a fresh heartbeat. We rely on fallback prices for sizing and let
    # the execution algorithm decide whether it can submit orders.
    return state in {"ok", "connected", "running", "degraded"}


def _pid_alive(pid: object) -> bool:
    try:
        pid_value = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_value <= 0:
        return False
    try:
        os.kill(pid_value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


_TERMINAL_RUN_STATUSES = {"done", "failed", "partial", "blocked", "canceled", "cancelled", "terminated"}


def _terminate_pid(pid: object, *, force: bool = False) -> bool:
    try:
        pid_value = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_value <= 0:
        return False
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.kill(pid_value, sig)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    except OSError:
        return False
    return True


def cleanup_terminal_run_processes(session, *, limit: int = 20) -> int:
    limit_value = max(1, int(limit))
    terminal_runs = (
        session.query(TradeRun)
        .filter(func.lower(TradeRun.status).in_(_TERMINAL_RUN_STATUSES))
        .order_by(TradeRun.updated_at.desc())
        .limit(limit_value)
        .all()
    )
    bridge_root = str(_resolve_bridge_root())
    cleaned = 0
    for run in terminal_runs:
        params = dict(run.params or {})
        lean_exec = params.get("lean_execution")
        if not isinstance(lean_exec, dict):
            continue
        pid = lean_exec.get("pid")
        if not _pid_alive(pid):
            continue
        source = str(lean_exec.get("source") or "").strip().lower()
        if source == "leader_command":
            continue
        output_dir = str(lean_exec.get("output_dir") or "").strip()
        # Never terminate the long-lived leader process from run-level cleanup.
        if output_dir and output_dir == bridge_root:
            continue

        terminated = _terminate_pid(pid, force=False)
        still_alive = _pid_alive(pid)
        if still_alive:
            _terminate_pid(pid, force=True)
            still_alive = _pid_alive(pid)

        cleaned += 1
        now_iso = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        cleanup_meta = dict(params.get("lean_execution_cleanup") or {})
        cleanup_meta.update(
            {
                "reason": "run_terminal_status",
                "pid": int(pid) if str(pid or "").strip() else None,
                "terminated_signal_sent": bool(terminated),
                "alive_after": bool(still_alive),
                "checked_at": now_iso,
            }
        )
        params["lean_execution_cleanup"] = cleanup_meta
        if not still_alive:
            lean_exec["pid"] = None
            lean_exec["terminated_at"] = now_iso
            lean_exec["terminated_reason"] = "run_terminal_status"
            params["lean_execution"] = lean_exec
        run.params = params
        run.updated_at = datetime.utcnow()
    return cleaned


def _resolve_lean_execution_log_path() -> Path:
    launcher_path = Path(settings.lean_launcher_path) if settings.lean_launcher_path else None
    if launcher_path:
        base = launcher_path.parent if launcher_path.is_file() else launcher_path
        candidate = base / "bin" / "Release" / "LeanBridgeExecutionAlgorithm-log.txt"
        if candidate.exists():
            return candidate
    return Path("/app/stocklean/Lean_git/Launcher/bin/Release/LeanBridgeExecutionAlgorithm-log.txt")


def _read_tail_text(path: Path, *, max_bytes: int = 400_000) -> str:
    try:
        size = path.stat().st_size
        offset = max(size - max_bytes, 0)
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
        return data.decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _lean_no_orders_submitted(run_id: int) -> bool:
    if not run_id:
        return False
    log_path = _resolve_lean_execution_log_path()
    if not log_path.exists():
        return False
    text = _read_tail_text(log_path)
    marker = f"oi_{run_id}_"
    pos = text.rfind(marker)
    if pos < 0:
        return False
    tail = text[pos:]
    if "LEAN_BRIDGE_NO_ORDERS_SUBMITTED" in tail:
        return True
    if "Quit(): no_orders_submitted" in tail:
        return True
    return False


def _lean_submit_blocked_during_warmup(run_id: int) -> bool:
    if not run_id:
        return False
    log_path = _resolve_lean_execution_log_path()
    if not log_path.exists():
        return False
    text = _read_tail_text(log_path)
    if not text:
        return False

    run_marker = f"trade_run_{run_id}.json"
    pos = text.rfind(run_marker)
    if pos >= 0:
        tail = text[pos:]
    else:
        intent_marker = f"oi_{run_id}_"
        pos = text.rfind(intent_marker)
        if pos < 0:
            return False
        tail = text[max(0, pos - 12_000) :]

    markers = (
        "This operation is not allowed in Initialize or during warm up: OrderRequest.Submit",
        "This operation is not allowed in Initialize or during warm-up: OrderRequest.Submit",
    )
    return any(marker in tail for marker in markers)


def _quote_price(item: dict[str, Any]) -> float | None:
    payload = item.get("data") if isinstance(item.get("data"), dict) else item
    return _pick_price(payload if isinstance(payload, dict) else None)


def _normalize_symbol_for_filename(symbol: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", "_", symbol.upper())
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


def _read_latest_close(path: Path) -> float | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            last_row: dict[str, Any] | None = None
            for row in reader:
                last_row = row
        if not last_row:
            return None
        close_value = last_row.get("close")
        if close_value is None or close_value == "":
            return None
        return float(close_value)
    except (OSError, ValueError, TypeError):
        return None


def _load_fallback_prices(symbols: list[str]) -> dict[str, float]:
    root = _resolve_data_root() / "curated_adjusted"
    prices: dict[str, float] = {}
    for symbol in symbols:
        path = _find_latest_price_file(root, symbol)
        if not path:
            continue
        price = _read_latest_close(path)
        if price is None or price <= 0:
            continue
        prices[symbol] = price
    return prices


def _build_price_map(symbols: list[str]) -> dict[str, float]:
    symbol_set = {symbol for symbol in symbols if symbol}
    quotes = read_quotes(_resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes.get("items"), list) else []
    prices: dict[str, float] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol or symbol not in symbol_set:
            continue
        price = _quote_price(item)
        if price is not None and price > 0:
            prices[symbol] = price
    missing = sorted(symbol_set - set(prices.keys()))
    if missing:
        prices.update(_load_fallback_prices(missing))
    return prices


def _finalize_run_status(session, run, *, filled: int, rejected: int, cancelled: int):
    if filled == 0:
        run.status = "failed"
    elif rejected or cancelled:
        run.status = "partial"
    else:
        run.status = "done"
    run.ended_at = datetime.utcnow()
    run.updated_at = datetime.utcnow()
    session.commit()


_TERMINAL_ORDER_STATUSES = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "INVALID", "SKIPPED"}
_CANCELLED_ORDER_STATUSES = {"CANCELED", "CANCELLED"}
_REJECTED_ORDER_STATUSES = {"REJECTED", "INVALID"}
_SKIPPED_ORDER_STATUSES = {"SKIPPED"}
_STALLED_WINDOW_MINUTES = 15
_LEADER_BRIDGE_READY_STATES = {"ok", "connected", "running", "degraded"}
_LEADER_COMMAND_STALE_SECONDS = 8
_LEADER_COMMAND_HISTORY_SECONDS = 300
_SUBMIT_COMMAND_PENDING_STALLED_SECONDS = 12
_OPEN_ORDERS_PAYLOAD_FRESH_SECONDS = 90
# Direct orders that timed out in leader-submit and were superseded to short-lived fallback
# can otherwise stay SUBMITTED forever when no further execution events arrive.
_DIRECT_SUPERSEDED_NO_FILL_FINALIZE_SECONDS = 900


def _normalize_order_status(value: str | None) -> str:
    return str(value or "").strip().upper()


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _extract_broker_order_id(result: dict[str, Any] | None) -> int | None:
    if not isinstance(result, dict):
        return None
    values = result.get("brokerage_ids")
    if isinstance(values, list):
        for value in values:
            try:
                parsed = int(str(value).strip())
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
    for key in ("order_id", "lean_order_id"):
        raw = result.get(key)
        try:
            parsed = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _is_open_orders_payload_fresh(
    payload: dict | None,
    *,
    now: datetime | None = None,
    max_age_seconds: int = _OPEN_ORDERS_PAYLOAD_FRESH_SECONDS,
) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("stale") is True:
        return False
    refreshed_dt = parse_bridge_timestamp(payload, ["refreshed_at", "updated_at"])
    if refreshed_dt is None:
        return False
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    else:
        clock = clock.astimezone(timezone.utc)
    try:
        age_seconds = float((clock - refreshed_dt).total_seconds())
    except Exception:
        return False
    return age_seconds <= max(0, int(max_age_seconds))


def _is_unfilled_management_enabled(params_path: object) -> bool:
    if not params_path:
        return False
    try:
        payload = json.loads(Path(str(params_path)).read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    try:
        timeout_s = int(payload.get("unfilled_timeout_seconds") or 0)
    except (TypeError, ValueError):
        timeout_s = 0
    try:
        interval_s = int(payload.get("unfilled_reprice_interval_seconds") or 0)
    except (TypeError, ValueError):
        interval_s = 0
    try:
        max_reprices = int(payload.get("unfilled_max_reprices") or 0)
    except (TypeError, ValueError):
        max_reprices = 0
    return timeout_s > 0 or (interval_s > 0 and max_reprices > 0)


def _apply_unfilled_management_launch_config(
    config: dict[str, Any],
    *,
    params_path: object,
) -> None:
    if not isinstance(config, dict):
        return
    if _is_unfilled_management_enabled(params_path):
        config["lean-bridge-exit-on-submit"] = False


def _should_use_leader_submit(params: dict[str, Any], orders: list[TradeOrder]) -> bool:
    explicit = params.get("submit_via_leader")
    if explicit is not None:
        return _as_bool(explicit, default=False)
    # Default behavior: enable only for Adaptive LMT batches.
    if not orders:
        return False
    for order in orders:
        if str(order.order_type or "").strip().upper() != "ADAPTIVE_LMT":
            return False
    return True


def _is_leader_command_channel_healthy(
    bridge_root: Path,
    *,
    stale_seconds: int = _LEADER_COMMAND_STALE_SECONDS,
    history_seconds: int = _LEADER_COMMAND_HISTORY_SECONDS,
) -> bool:
    commands_dir = Path(bridge_root) / "commands"
    if not commands_dir.exists():
        return True
    now_ts = datetime.now(timezone.utc).timestamp()
    threshold = max(1, int(stale_seconds))
    recent_horizon = max(threshold + 1, int(history_seconds))
    try:
        pending_files = list(commands_dir.glob("submit_order_*.json"))
    except Exception:
        return False
    # Ignore historical leftovers (already expired/dead commands) and only treat recent stale
    # submit requests as unhealthy. This prevents old artifacts from permanently disabling
    # leader submission.
    def _mtime(value: Path) -> float:
        try:
            return float(value.stat().st_mtime)
        except OSError:
            return 0.0

    for path in sorted(pending_files, key=_mtime, reverse=True)[:400]:
        try:
            age = now_ts - float(path.stat().st_mtime)
        except OSError:
            continue
        if age < 0:
            age = 0.0
        if age > float(recent_horizon):
            continue
        if age >= threshold:
            return False
    return True


def _is_bridge_ready_for_submit(bridge_root: Path) -> bool:
    status = read_bridge_status(bridge_root)
    state = str(status.get("status") or "").strip().lower()
    if status.get("stale") is True:
        return False
    if state not in _LEADER_BRIDGE_READY_STATES:
        return False
    return _is_leader_command_channel_healthy(bridge_root)


def _leader_submit_fallback_reason(bridge_root: Path) -> str:
    try:
        status = read_bridge_status(bridge_root)
    except Exception:
        return "bridge_status_unavailable"
    if not isinstance(status, dict):
        return "bridge_status_unavailable"
    if status.get("stale") is True:
        return "bridge_status_stale"
    state = str(status.get("status") or "").strip().lower()
    if state not in _LEADER_BRIDGE_READY_STATES:
        return f"bridge_status_{state or 'unknown'}"
    if not _is_leader_command_channel_healthy(bridge_root):
        return "command_channel_unhealthy"
    return "bridge_not_ready"


def _submit_run_orders_via_leader(
    session,
    *,
    run: TradeRun,
    orders: list[TradeOrder],
    params: dict[str, Any],
    bridge_root: Path,
) -> dict[str, Any]:
    commands_dir = bridge_root / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.utcnow().isoformat() + "Z"
    adaptive_priority = str(params.get("adaptive_priority") or "Normal").strip() or "Normal"
    run_meta: dict[str, Any] = {
        "source": "leader_command",
        "submitted_at": now,
        "mode": run.mode,
        "output_dir": str(bridge_root),
        "commands": [],
    }

    for order in orders:
        qty = float(order.quantity or 0.0)
        if qty <= 0:
            continue
        side = str(order.side or "").strip().upper()
        signed_qty = qty if side == "BUY" else -qty
        cmd = write_submit_order_command(
            commands_dir,
            symbol=order.symbol,
            quantity=signed_qty,
            tag=order.client_order_id,
            order_type=order.order_type or "MKT",
            order_id=order.id,
            limit_price=order.limit_price,
            outside_rth=_as_bool(params.get("allow_outside_rth"), default=False),
            adaptive_priority=adaptive_priority,
            actor="trade_executor",
            reason=f"trade_run_{run.id}",
            expires_seconds=120,
        )
        order_params = dict(order.params or {})
        order_params["submit_command"] = {
            "pending": True,
            "command_id": cmd.command_id,
            "command_path": cmd.command_path,
            "requested_at": cmd.requested_at,
            "expires_at": cmd.expires_at,
            "source": "leader_command",
        }
        order_params["event_source"] = "lean_command"
        order.params = order_params
        run_meta["commands"].append(
            {
                "order_id": order.id,
                "symbol": order.symbol,
                "command_id": cmd.command_id,
                "command_path": cmd.command_path,
            }
        )

    return run_meta


def _reconcile_submit_command_results(session, run: TradeRun, *, bridge_root: Path) -> int:
    updated = 0
    orders = (
        session.query(TradeOrder)
        .filter(TradeOrder.run_id == run.id)
        .order_by(TradeOrder.id.asc())
        .all()
    )
    for order in orders:
        params = dict(order.params or {})
        submit_meta = params.get("submit_command")
        if not isinstance(submit_meta, dict) or not _as_bool(submit_meta.get("pending"), default=False):
            continue
        command_id = str(submit_meta.get("command_id") or "").strip()
        if not command_id:
            continue
        result_path = bridge_root / "command_results" / f"{command_id}.json"
        if not result_path.exists():
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(result, dict):
            continue
        status = str(result.get("status") or "").strip().lower()
        processed_at = result.get("processed_at")
        merged_submit = dict(submit_meta)
        merged_submit["pending"] = False
        merged_submit["status"] = status
        if processed_at:
            merged_submit["processed_at"] = processed_at
        payload_params = {
            "submit_command": merged_submit,
            "event_source": "lean_command",
            "sync_reason": f"submit_command_{status or 'unknown'}",
        }
        broker_order_id = _extract_broker_order_id(result)
        if broker_order_id is not None and order.ib_order_id is None:
            order.ib_order_id = int(broker_order_id)

        if status == "submitted":
            current = str(order.status or "").strip().upper()
            if current == "NEW":
                try:
                    update_trade_order_status(
                        session,
                        order,
                        {"status": "SUBMITTED", "params": payload_params},
                    )
                except ValueError:
                    force_update_trade_order_status(
                        session,
                        order,
                        {"status": "SUBMITTED", "params": payload_params},
                    )
            else:
                force_update_trade_order_status(
                    session,
                    order,
                    {"status": current or "SUBMITTED", "params": payload_params},
                )
            updated += 1
            continue

        if status in {
            "invalid",
            "place_failed",
            "not_connected",
            "expired",
            "parse_error",
            "symbol_invalid",
            "quantity_invalid",
            "unsupported_order_type",
            "limit_price_invalid",
        }:
            reason = str(result.get("error") or status)
            try:
                update_trade_order_status(
                    session,
                    order,
                    {"status": "REJECTED", "params": {**payload_params, "reason": reason}},
                )
            except ValueError:
                force_update_trade_order_status(
                    session,
                    order,
                    {"status": "REJECTED", "params": {**payload_params, "reason": reason}, "rejected_reason": reason},
                )
            updated += 1
    return updated


def _collect_timed_out_submit_pending_orders(
    session,
    run: TradeRun,
    *,
    now: datetime,
    timeout_seconds: int = _SUBMIT_COMMAND_PENDING_STALLED_SECONDS,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "checked": 0,
        "pending": 0,
        "timed_out": 0,
        "oldest_age_seconds": 0.0,
        "orders": [],
    }
    threshold = max(1, int(timeout_seconds))
    clock = now
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    else:
        clock = clock.astimezone(timezone.utc)
    active_source = ""
    if isinstance(run.params, dict):
        lean_exec = run.params.get("lean_execution")
        if isinstance(lean_exec, dict):
            active_source = str(lean_exec.get("source") or "").strip().lower()
    orders = (
        session.query(TradeOrder)
        .filter(TradeOrder.run_id == run.id, TradeOrder.status == "NEW")
        .order_by(TradeOrder.id.asc())
        .all()
    )
    for order in orders:
        summary["checked"] += 1
        params = dict(order.params or {})
        submit_meta = params.get("submit_command")
        if not isinstance(submit_meta, dict) or not _as_bool(submit_meta.get("pending"), default=False):
            continue
        submit_source = str(submit_meta.get("source") or "").strip().lower()
        # Once a run switched to short-lived fallback, historical leader command metadata
        # should no longer participate in pending timeout checks.
        if active_source and active_source != "leader_command" and submit_source in {"", "leader_command"}:
            continue
        summary["pending"] += 1
        requested_dt = parse_bridge_timestamp(submit_meta, ["requested_at"])
        if requested_dt is None:
            requested_dt = getattr(order, "created_at", None) or getattr(order, "updated_at", None)
        if isinstance(requested_dt, datetime):
            if requested_dt.tzinfo is None:
                requested_dt = requested_dt.replace(tzinfo=timezone.utc)
            else:
                requested_dt = requested_dt.astimezone(timezone.utc)
        if not isinstance(requested_dt, datetime):
            continue
        try:
            age_seconds = float((clock - requested_dt).total_seconds())
        except Exception:
            continue
        if age_seconds > float(summary["oldest_age_seconds"] or 0.0):
            summary["oldest_age_seconds"] = age_seconds
        if age_seconds < threshold:
            continue
        summary["timed_out"] += 1
        summary["orders"].append(
            {
                "order_id": int(order.id),
                "symbol": str(order.symbol or "").strip().upper(),
                "command_id": str(submit_meta.get("command_id") or ""),
                "requested_at": submit_meta.get("requested_at"),
                "age_seconds": round(age_seconds, 3),
            }
        )
    return summary


def _clear_leader_submit_pending_after_fallback(
    session,
    run: TradeRun,
    *,
    resolved_at: datetime,
    reason: str,
) -> int:
    resolved = resolved_at
    if resolved.tzinfo is None:
        resolved = resolved.replace(tzinfo=timezone.utc)
    else:
        resolved = resolved.astimezone(timezone.utc)
    resolved_text = resolved.isoformat().replace("+00:00", "Z")
    updated = 0
    orders = (
        session.query(TradeOrder)
        .filter(TradeOrder.run_id == run.id, TradeOrder.status == "NEW")
        .order_by(TradeOrder.id.asc())
        .all()
    )
    for order in orders:
        params = dict(order.params or {})
        submit_meta = params.get("submit_command")
        if not isinstance(submit_meta, dict) or not _as_bool(submit_meta.get("pending"), default=False):
            continue
        source = str(submit_meta.get("source") or "").strip().lower()
        if source and source != "leader_command":
            continue
        merged_submit = dict(submit_meta)
        merged_submit["pending"] = False
        merged_submit["status"] = "superseded"
        merged_submit.setdefault("processed_at", resolved_text)
        merged_submit["reason"] = reason
        merged_submit["superseded_by"] = "short_lived_fallback"
        params["submit_command"] = merged_submit
        params["event_source"] = "lean_command"
        params["sync_reason"] = "leader_submit_superseded"
        order.params = params
        order.updated_at = datetime.utcnow()
        updated += 1
    return updated


def _launch_short_lived_fallback_for_leader_submit(
    session,
    run: TradeRun,
    *,
    reason: str,
    now: datetime,
) -> bool:
    params = dict(run.params or {})
    intent_path = str(params.get("order_intent_path") or "").strip()
    if not intent_path:
        return False

    exec_output_dir = ARTIFACT_ROOT / "lean_bridge_runs" / f"run_{run.id}"
    config = build_execution_config(
        intent_path=intent_path,
        brokerage="InteractiveBrokersBrokerage",
        project_id=run.project_id,
        mode=run.mode,
        params_path=params.get("execution_params_path"),
        lean_bridge_output_dir=str(exec_output_dir),
    )
    # Keep fallback executor alive when unfilled management is enabled so it can keep emitting
    # order events (filled/canceled/repriced) instead of exiting right after submit ack.
    _apply_unfilled_management_launch_config(
        config,
        params_path=params.get("execution_params_path"),
    )
    config_dir = ARTIFACT_ROOT / "lean_execution"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"trade_run_{run.id}_fallback.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    pid = launch_execution_async(config_path=str(config_path))

    submitted_at = now
    if submitted_at.tzinfo is None:
        submitted_at = submitted_at.replace(tzinfo=timezone.utc)
    else:
        submitted_at = submitted_at.astimezone(timezone.utc)

    lean_exec = dict(params.get("lean_execution") or {})
    previous_source = str(lean_exec.get("source") or "").strip() or None
    lean_exec.update(
        {
            "source": "short_lived_fallback",
            "fallback_reason": reason,
            "previous_source": previous_source,
            "config_path": str(config_path),
            "pid": int(pid),
            "output_dir": str(exec_output_dir),
            "submitted_at": submitted_at.isoformat().replace("+00:00", "Z"),
        }
    )
    params["lean_execution"] = lean_exec
    cleared_pending = _clear_leader_submit_pending_after_fallback(
        session,
        run,
        resolved_at=submitted_at,
        reason=reason,
    )
    params["leader_submit_runtime_fallback"] = {
        "triggered": True,
        "reason": reason,
        "triggered_at": submitted_at.isoformat().replace("+00:00", "Z"),
        "cleared_pending_orders": int(cleared_pending),
    }
    run.params = params
    run.status = "running"
    run.message = "submitted_lean_fallback"
    run.stalled_at = None
    run.stalled_reason = None
    run.updated_at = now
    session.commit()
    update_trade_run_progress(session, run, "submitted_lean_fallback", reason=reason, commit=True)
    return True


def determine_run_status(order_statuses: list[str]) -> tuple[str | None, dict[str, int]]:
    normalized = [_normalize_order_status(status) for status in order_statuses if status is not None]
    total = len(normalized)
    summary = {"total": total, "filled": 0, "cancelled": 0, "rejected": 0, "skipped": 0}
    if not normalized:
        return None, summary
    if any(status not in _TERMINAL_ORDER_STATUSES for status in normalized):
        for status in normalized:
            if status == "FILLED":
                summary["filled"] += 1
            elif status in _CANCELLED_ORDER_STATUSES:
                summary["cancelled"] += 1
            elif status in _REJECTED_ORDER_STATUSES:
                summary["rejected"] += 1
            elif status in _SKIPPED_ORDER_STATUSES:
                summary["skipped"] += 1
        return None, summary
    for status in normalized:
        if status == "FILLED":
            summary["filled"] += 1
        elif status in _CANCELLED_ORDER_STATUSES:
            summary["cancelled"] += 1
        elif status in _REJECTED_ORDER_STATUSES:
            summary["rejected"] += 1
        elif status in _SKIPPED_ORDER_STATUSES:
            summary["skipped"] += 1
    if summary["filled"] == 0 and (summary["rejected"] + summary["cancelled"] + summary["skipped"]) > 0:
        return "failed", summary
    if summary["rejected"] > 0 or summary["cancelled"] > 0 or summary["skipped"] > 0:
        return "partial", summary
    return "done", summary


def recompute_trade_run_completion_summary(session, run: TradeRun) -> bool:
    """Recompute `run.status` and `run.params.completion_summary` from persisted TradeOrder statuses.

    This is intentionally *order-driven* (not event-driven) and can be used to correct runs whose
    completion summary drifted after late reconciliation (e.g. positions-based fills inferred after
    the run was previously marked failed/partial).
    """
    if session is None or run is None:
        return False

    statuses = [
        row[0]
        for row in session.query(TradeOrder.status).filter(TradeOrder.run_id == run.id).all()
    ]
    computed_status, summary = determine_run_status(statuses)

    params = dict(run.params or {})
    prev_summary = params.get("completion_summary")
    changed = prev_summary != summary

    if computed_status is not None:
        current_status = str(run.status or "").strip().lower()
        next_status = str(computed_status).strip().lower()
        if current_status != next_status:
            # Don't override explicit operator actions (manual terminate/resume/etc.).
            message = str(run.message or "").strip().lower()
            if not message.startswith("manual_"):
                run.status = computed_status
                if run.ended_at is None:
                    run.ended_at = datetime.utcnow()
                changed = True

    if not changed:
        return False

    params["completion_summary"] = summary
    params["completion_summary_recomputed_at"] = datetime.utcnow().isoformat() + "Z"
    run.params = params
    run.updated_at = datetime.utcnow()
    session.commit()
    return True


def _should_skip_order_build(execution_source: str | None) -> bool:
    return str(execution_source or "").strip().lower() == "lean"


def _build_positions_map(positions_payload: dict | None) -> dict[str, dict[str, float | None]]:
    if not isinstance(positions_payload, dict):
        return {}
    items = positions_payload.get("items") if isinstance(positions_payload.get("items"), list) else []
    positions: dict[str, dict[str, float | None]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        quantity_value = item.get("quantity")
        if quantity_value is None:
            quantity_value = item.get("position")
        if quantity_value is None:
            continue
        try:
            quantity = float(quantity_value)
        except (TypeError, ValueError):
            continue
        avg_cost_value = item.get("avg_cost")
        avg_cost = None
        if avg_cost_value is not None:
            try:
                avg_cost = float(avg_cost_value)
            except (TypeError, ValueError):
                avg_cost = None
        positions[symbol] = {"quantity": quantity, "avg_cost": avg_cost}
    return positions


def _load_order_intent_items(path: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _extract_intent_symbols(items: list[dict[str, Any]]) -> list[str]:
    symbols = []
    seen = set()
    for item in items:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def _build_sized_qty_map_from_intent(
    intent_path: str,
    *,
    price_map: dict[str, float],
    portfolio_value: float,
    cash_buffer_ratio: float,
    lot_size: int,
    min_qty: int,
) -> dict[tuple[str, str], int]:
    items = _load_order_intent_items(intent_path)
    if not items:
        return {}
    sized = build_orders(
        items,
        price_map=price_map,
        portfolio_value=portfolio_value,
        cash_buffer_ratio=cash_buffer_ratio,
        lot_size=lot_size,
        order_type="MKT",
        limit_price=None,
        min_qty=min_qty,
    )
    out: dict[tuple[str, str], int] = {}
    for draft in sized:
        symbol = str(draft.get("symbol") or "").strip().upper()
        side = str(draft.get("side") or "").strip().upper()
        qty = draft.get("quantity")
        if not symbol or not side:
            continue
        try:
            qty_value = int(qty)
        except (TypeError, ValueError):
            continue
        if qty_value <= 0:
            continue
        out[(symbol, side)] = qty_value
    return out


def enforce_intent_order_match(
    session,
    run: TradeRun,
    orders: list[TradeOrder],
    intent_path: str,
) -> bool:
    if not intent_path:
        return True
    items = _load_order_intent_items(intent_path)
    expected_symbols = _extract_intent_symbols(items)
    if not expected_symbols:
        return True
    created_symbols = sorted({str(order.symbol or "").strip().upper() for order in orders if order.symbol})
    expected_set = set(expected_symbols)
    created_set = set(created_symbols)
    missing = sorted(expected_set - created_set)
    extra = sorted(created_set - expected_set)
    if not missing and not extra:
        return True
    params = dict(run.params or {})
    params["intent_order_mismatch"] = {
        "intent_path": intent_path,
        "expected_symbols": sorted(expected_set),
        "created_symbols": created_symbols,
        "missing_symbols": missing,
        "extra_symbols": extra,
    }
    run.params = params
    run.message = "intent_order_mismatch"
    record_audit(
        session,
        action="trade_run.intent_order_mismatch",
        resource_type="trade_run",
        resource_id=run.id,
        detail=params["intent_order_mismatch"],
    )
    force_close_run(session, run, reason="intent_order_mismatch")
    return False


def _extract_open_tags(open_orders_payload: dict | None) -> set[str]:
    if not isinstance(open_orders_payload, dict):
        return set()
    items = open_orders_payload.get("items") if isinstance(open_orders_payload.get("items"), list) else []
    tags: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag") or "").strip()
        if tag:
            tags.add(tag)
    return tags


def _load_positions_baseline(run: TradeRun | None) -> dict[str, float]:
    if run is None or not isinstance(run.params, dict):
        return {}
    baseline = run.params.get("positions_baseline")
    if not isinstance(baseline, dict):
        return {}
    items = baseline.get("items") if isinstance(baseline.get("items"), list) else []
    out: dict[str, float] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        try:
            qty = float(item.get("quantity") or 0.0)
        except (TypeError, ValueError):
            qty = 0.0
        out[symbol] = qty
    return out


def reconcile_run_with_positions(
    session,
    run: TradeRun,
    positions_payload: dict | None,
    *,
    open_tags: set[str] | None = None,
) -> dict[str, int]:
    summary = {"checked": 0, "reconciled": 0, "skipped": 0}
    if run is None or not isinstance(positions_payload, dict):
        return summary
    if positions_payload.get("stale") is True:
        return summary
    baseline = _load_positions_baseline(run)
    if not baseline:
        # Without a pre-run baseline we can't safely infer fills from holdings (would treat
        # already-held positions as filled orders).
        return summary
    positions = _build_positions_map(positions_payload)
    if not positions:
        return summary
    orders = session.query(TradeOrder).filter(TradeOrder.run_id == run.id).all()
    for order in orders:
        status = _normalize_order_status(order.status)
        params = order.params if isinstance(order.params, dict) else {}
        sync_reason = str(params.get("sync_reason") or "").strip()
        event_source = str(params.get("event_source") or "").strip()
        low_conf_missing = (
            status in {"CANCELED", "CANCELLED", "SKIPPED"}
            and (
                (event_source == "lean_open_orders" and sync_reason == "missing_from_open_orders")
                or (
                    event_source == "lean_command"
                    and sync_reason in {"cancel_command_ok", "cancel_command_not_found"}
                )
            )
        )
        if status in _TERMINAL_ORDER_STATUSES and not low_conf_missing:
            continue
        summary["checked"] += 1
        tag = str(order.client_order_id or "").strip()
        if open_tags and tag and tag in open_tags:
            # Still present in IB open orders, so do not infer terminal fills from holdings yet.
            summary["skipped"] += 1
            continue
        pos = positions.get(str(order.symbol or "").strip().upper())
        if not pos:
            summary["skipped"] += 1
            continue
        pos_qty = float(pos.get("quantity") or 0.0)
        symbol_key = str(order.symbol or "").strip().upper()
        base_qty = float(baseline.get(symbol_key, 0.0))

        side = str(order.side or "").strip().upper()
        if side == "BUY":
            delta = pos_qty - base_qty
        elif side == "SELL":
            delta = base_qty - pos_qty
        else:
            summary["skipped"] += 1
            continue
        if delta <= 0:
            summary["skipped"] += 1
            continue
        target_filled = min(float(order.quantity), float(delta))
        prev_filled = float(order.filled_quantity or 0.0)
        if target_filled <= prev_filled + 1e-6:
            summary["skipped"] += 1
            continue
        incremental = target_filled - prev_filled

        # Idempotency: exec_id is deterministic for a given reconciled filled-quantity watermark.
        watermark = int(round(target_filled * 1_000_000))
        exec_id = f"positions_reconcile:{order.id}:{watermark}"
        if (
            session.query(TradeFill)
            .filter(TradeFill.order_id == order.id, TradeFill.exec_id == exec_id)
            .first()
            is not None
        ):
            summary["skipped"] += 1
            continue
        fill_price = pos.get("avg_cost")
        if not fill_price or float(fill_price) <= 0:
            fallback = order.avg_fill_price or order.limit_price
            if fallback is not None:
                fill_price = float(fallback)
        if not fill_price or float(fill_price) <= 0:
            summary["skipped"] += 1
            continue
        current_status = _normalize_order_status(order.status)
        if current_status == "NEW":
            update_trade_order_status(session, order, {"status": "SUBMITTED"})
        total_new = target_filled
        avg_prev = float(order.avg_fill_price or 0.0)
        avg_new = (avg_prev * prev_filled + float(fill_price) * incremental) / total_new
        target_status = "PARTIAL" if total_new + 1e-6 < float(order.quantity) else "FILLED"
        updater = force_update_trade_order_status if low_conf_missing else update_trade_order_status
        event_time = datetime.utcnow().isoformat() + "Z"
        reconcile_params = {
            "reconcile_source": "positions",
            "baseline_quantity": base_qty,
            "current_position_quantity": pos_qty,
            # Override low-confidence sync metadata so the UI matches IB/TWS reality.
            "event_source": "positions",
            "event_status": target_status,
            "event_time": event_time,
            "sync_reason": "positions_reconcile",
        }
        if low_conf_missing:
            reconcile_params["reconcile_recovered_from"] = status
        updater(
            session,
            order,
            {
                "status": target_status,
                "filled_quantity": total_new,
                "avg_fill_price": avg_new,
                "params": reconcile_params,
            },
        )
        fill = TradeFill(
            order_id=order.id,
            exec_id=exec_id,
            fill_quantity=float(incremental),
            fill_price=float(fill_price),
            commission=None,
            fill_time=datetime.utcnow(),
            params={
                "source": "positions_reconcile",
                "baseline_quantity": base_qty,
                "current_position_quantity": pos_qty,
            },
        )
        session.add(fill)
        session.commit()
        summary["reconciled"] += 1
    return summary


def _load_direct_positions_baseline(order: TradeOrder) -> tuple[float | None, str | None, float | None]:
    """Best-effort baseline qty for direct (run_id=None) orders.

    Primary source: `order.params.positions_baseline` if present.
    Fallback source: the direct executor's Lean bridge output dir:
      `{bridge_root}/direct_{order.id}/positions.json`
    """
    if order is None:
        return None, None, None
    symbol = str(order.symbol or "").strip().upper()
    if not symbol:
        return None, None, None

    params = order.params if isinstance(order.params, dict) else {}
    baseline = params.get("positions_baseline")
    if isinstance(baseline, dict):
        items = baseline.get("items") if isinstance(baseline.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("symbol") or "").strip().upper() != symbol:
                continue
            try:
                qty = float(item.get("quantity") or 0.0)
            except (TypeError, ValueError):
                qty = None
            avg_cost_value = item.get("avg_cost")
            try:
                avg_cost = float(avg_cost_value) if avg_cost_value is not None else None
            except (TypeError, ValueError):
                avg_cost = None
            return qty, str(baseline.get("refreshed_at") or "") or None, avg_cost

    # Fallback: read the executor's snapshot at submission time.
    try:
        bridge_root = _resolve_bridge_root()
    except Exception:
        bridge_root = None
    if bridge_root is None:
        return None, None, None
    try:
        path = Path(str(bridge_root)) / f"direct_{int(order.id)}" / "positions.json"
    except Exception:
        return None, None, None
    if not path.exists():
        return None, None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None, None
    if not isinstance(payload, dict) or payload.get("stale") is True:
        return None, None, None
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("symbol") or "").strip().upper() != symbol:
            continue
        qty_value = item.get("quantity")
        if qty_value is None:
            qty_value = item.get("position")
        if qty_value is None:
            continue
        try:
            qty = float(qty_value)
        except (TypeError, ValueError):
            continue
        avg_cost_value = item.get("avg_cost")
        try:
            avg_cost = float(avg_cost_value) if avg_cost_value is not None else None
        except (TypeError, ValueError):
            avg_cost = None
        return qty, str(payload.get("refreshed_at") or payload.get("updated_at") or "") or None, avg_cost

    return None, None, None


def reconcile_direct_orders_with_positions(
    session,
    positions_payload: dict | None,
    *,
    open_tags: set[str] | None = None,
    now: datetime | None = None,
    min_age_seconds: int = 120,
) -> dict[str, int]:
    """Infer fills for direct orders whose execution client already exited.

    Direct orders (run_id=None) may be submitted by short-lived Lean execution processes which
    exit after submission. If the order fills later (e.g., MarketOnOpen at the next session),
    we won't have execution events. We can still infer fills using a pre-submit baseline qty
    captured by the executor positions snapshot.
    """
    summary = {"checked": 0, "reconciled": 0, "terminalized_no_fill_timeout": 0, "skipped": 0}
    if session is None or not isinstance(positions_payload, dict):
        return summary
    if positions_payload.get("stale") is True:
        return summary
    positions = _build_positions_map(positions_payload)

    clock = now or datetime.utcnow()
    orders = (
        session.query(TradeOrder)
        .filter(
            TradeOrder.run_id.is_(None),
            TradeOrder.status.in_(["NEW", "SUBMITTED", "PARTIAL", "CANCEL_REQUESTED", "CANCELED", "CANCELLED", "SKIPPED"]),
        )
        .order_by(TradeOrder.id.asc())
        .all()
    )
    for order in orders:
        status = _normalize_order_status(order.status)
        params = dict(order.params or {})
        low_conf_missing = (
            status in {"CANCELED", "CANCELLED", "SKIPPED"}
            and str(params.get("sync_reason") or "").strip() == "missing_from_open_orders"
        )
        if status in _TERMINAL_ORDER_STATUSES and not low_conf_missing:
            continue

        order_age_seconds: float | None = None
        created_at = getattr(order, "created_at", None) or getattr(order, "updated_at", None)
        if isinstance(created_at, datetime):
            created_dt = created_at
            try:
                order_age_seconds = (clock - created_dt).total_seconds()
            except Exception:
                order_age_seconds = None
            if order_age_seconds is not None and order_age_seconds < max(0, int(min_age_seconds)):
                summary["skipped"] += 1
                continue

        summary["checked"] += 1
        tag = None
        if isinstance(params, dict):
            tag = str(params.get("event_tag") or "").strip()
        if not tag:
            tag = str(order.client_order_id or "").strip()
        if open_tags and tag and tag in open_tags:
            summary["skipped"] += 1
            continue

        symbol_key = str(order.symbol or "").strip().upper()
        pos = positions.get(symbol_key)
        pos_qty = float(pos.get("quantity") or 0.0) if isinstance(pos, dict) else 0.0

        baseline_qty, baseline_refreshed, baseline_avg_cost = _load_direct_positions_baseline(order)
        if baseline_qty is None:
            summary["skipped"] += 1
            continue

        side = str(order.side or "").strip().upper()
        if side == "BUY":
            delta = pos_qty - float(baseline_qty)
        elif side == "SELL":
            delta = float(baseline_qty) - pos_qty
        else:
            summary["skipped"] += 1
            continue
        if delta <= 0:
            submit_meta = params.get("submit_command")
            submit_status = str(submit_meta.get("status") or "").strip().lower() if isinstance(submit_meta, dict) else ""
            submit_source = str(submit_meta.get("source") or "").strip().lower() if isinstance(submit_meta, dict) else ""
            submit_reason = str(submit_meta.get("reason") or "").strip().lower() if isinstance(submit_meta, dict) else ""
            timed_out_reason = submit_reason == "leader_submit_pending_timeout" or submit_reason.endswith(
                "pending_timeout"
            )
            should_finalize_no_fill = (
                status in {"SUBMITTED", "PARTIAL"}
                and submit_status == "superseded"
                and (not submit_source or submit_source == "leader_command")
                and timed_out_reason
                and order_age_seconds is not None
                and order_age_seconds >= float(_DIRECT_SUPERSEDED_NO_FILL_FINALIZE_SECONDS)
            )
            if should_finalize_no_fill:
                event_time = datetime.utcnow().isoformat() + "Z"
                try:
                    update_trade_order_status(
                        session,
                        order,
                        {
                            "status": "CANCELED",
                            "params": {
                                "reconcile_source": "positions_direct",
                                "baseline_quantity": float(baseline_qty),
                                "baseline_refreshed_at": baseline_refreshed,
                                "current_position_quantity": pos_qty,
                                "event_source": "positions",
                                "event_status": "CANCELED",
                                "event_time": event_time,
                                "sync_reason": "leader_submit_no_fill_timeout",
                                "no_fill_timeout_seconds": int(_DIRECT_SUPERSEDED_NO_FILL_FINALIZE_SECONDS),
                                "submit_command_status": submit_status,
                                "submit_command_reason": submit_reason,
                                "open_order_visible": False,
                            },
                        },
                    )
                except ValueError:
                    summary["skipped"] += 1
                else:
                    summary["terminalized_no_fill_timeout"] += 1
                continue
            summary["skipped"] += 1
            continue

        target_filled = min(float(order.quantity), float(delta))
        prev_filled = float(order.filled_quantity or 0.0)
        if target_filled <= prev_filled + 1e-6:
            summary["skipped"] += 1
            continue
        incremental = target_filled - prev_filled

        watermark = int(round(target_filled * 1_000_000))
        exec_id = f"positions_reconcile_direct:{order.id}:{watermark}"
        if (
            session.query(TradeFill)
            .filter(TradeFill.order_id == order.id, TradeFill.exec_id == exec_id)
            .first()
            is not None
        ):
            summary["skipped"] += 1
            continue

        fill_price = pos.get("avg_cost") if isinstance(pos, dict) else None
        if not fill_price or float(fill_price) <= 0:
            fallback = order.avg_fill_price or order.limit_price or baseline_avg_cost
            if fallback is not None:
                try:
                    fill_price = float(fallback)
                except (TypeError, ValueError):
                    fill_price = None
        if not fill_price or float(fill_price) <= 0:
            summary["skipped"] += 1
            continue

        if status == "NEW":
            update_trade_order_status(session, order, {"status": "SUBMITTED"})
        total_new = target_filled
        avg_prev = float(order.avg_fill_price or 0.0)
        avg_new = (avg_prev * prev_filled + float(fill_price) * incremental) / total_new
        target_status = "PARTIAL" if total_new + 1e-6 < float(order.quantity) else "FILLED"
        event_time = datetime.utcnow().isoformat() + "Z"
        update_params = {
            "reconcile_source": "positions_direct",
            "baseline_quantity": float(baseline_qty),
            "baseline_refreshed_at": baseline_refreshed,
            "current_position_quantity": pos_qty,
            "event_source": "positions",
            "event_status": target_status,
            "event_time": event_time,
            "sync_reason": "positions_reconcile",
        }
        if low_conf_missing:
            update_params["reconcile_recovered_from"] = status
        updater = force_update_trade_order_status if low_conf_missing else update_trade_order_status
        updater(
            session,
            order,
            {
                "status": target_status,
                "filled_quantity": total_new,
                "avg_fill_price": avg_new,
                "params": update_params,
            },
        )
        fill = TradeFill(
            order_id=order.id,
            exec_id=exec_id,
            fill_quantity=float(incremental),
            fill_price=float(fill_price),
            commission=None,
            fill_time=datetime.utcnow(),
            params={
                "source": "positions_reconcile_direct",
                "baseline_quantity": float(baseline_qty),
                "baseline_refreshed_at": baseline_refreshed,
                "current_position_quantity": pos_qty,
            },
        )
        session.add(fill)
        session.commit()
        summary["reconciled"] += 1

    return summary


def force_close_run(session, run: TradeRun, *, reason: str | None = None) -> dict[str, int]:
    summary = {"total": 0, "filled": 0, "cancelled": 0, "rejected": 0}
    if run is None:
        return summary
    orders = session.query(TradeOrder).filter(TradeOrder.run_id == run.id).all()
    for order in orders:
        status = _normalize_order_status(order.status)
        summary["total"] += 1
        if status == "FILLED":
            summary["filled"] += 1
            continue
        if status in _REJECTED_ORDER_STATUSES:
            summary["rejected"] += 1
            continue
        if status in _TERMINAL_ORDER_STATUSES:
            summary["cancelled"] += 1
            continue
        if status == "NEW":
            update_trade_order_status(session, order, {"status": "SUBMITTED"})
        update_trade_order_status(session, order, {"status": "CANCELED"})
        summary["cancelled"] += 1
    now = datetime.utcnow()
    run.status = "failed"
    run.ended_at = now
    run.updated_at = now
    run.stalled_at = None
    run.stalled_reason = None
    params = dict(run.params or {})
    params["completion_summary"] = summary
    params["force_closed"] = True
    if reason:
        params["force_close_reason"] = reason
    run.params = params
    if not run.message or run.message in {"submitted_lean", "submitted_leader", "stalled"}:
        run.message = "force_closed"
    session.commit()
    record_audit(
        session,
        action="trade_run.force_closed",
        resource_type="trade_run",
        resource_id=run.id,
        detail={
            "reason": reason,
            "summary": summary,
        },
    )
    return summary


def refresh_trade_run_status(session, run: TradeRun) -> bool:
    active_status = str(run.status or "").lower()
    if active_status not in {"running", "stalled"}:
        return False
    bridge_root = _resolve_bridge_root()
    # Ingest per-run execution events if available.
    exec_output_dir = None
    if isinstance(run.params, dict):
        lean_exec = run.params.get("lean_execution")
        if isinstance(lean_exec, dict):
            exec_output_dir = lean_exec.get("output_dir") or None
    if exec_output_dir:
        events_path = Path(str(exec_output_dir)) / "execution_events.jsonl"
        if events_path.exists():
            ingest_execution_events(str(events_path), session=session)
    _reconcile_submit_command_results(session, run, bridge_root=bridge_root)
    # Prefer run-scoped open orders snapshot (correct client-id coverage). Fallback to the
    # leader snapshot when the run snapshot is missing/stale.
    run_root = Path(str(exec_output_dir)) if exec_output_dir else None
    run_open_orders = read_open_orders(run_root) if run_root else None
    leader_open_orders = read_open_orders(bridge_root)
    run_payload_fresh = _is_open_orders_payload_fresh(run_open_orders)
    open_orders_payload = run_open_orders if run_payload_fresh else leader_open_orders
    open_tags = (
        _extract_open_tags(open_orders_payload)
        if _is_open_orders_payload_fresh(open_orders_payload)
        else set()
    )
    # Avoid prematurely cancelling newly-created orders: if the open-orders snapshot is older than the
    # Lean execution submission timestamp, it can't include those orders yet.
    submitted_at = None
    lean_pid = None
    if isinstance(run.params, dict):
        lean_exec = run.params.get("lean_execution")
        if isinstance(lean_exec, dict):
            submitted_at = lean_exec.get("submitted_at")
            lean_pid = lean_exec.get("pid")
    submitted_dt = parse_bridge_timestamp({"submitted_at": submitted_at}, ["submitted_at"])
    open_refreshed_dt = parse_bridge_timestamp(open_orders_payload, ["refreshed_at", "updated_at"])
    executor_alive = _pid_alive(lean_pid)
    if not (submitted_dt and open_refreshed_dt and open_refreshed_dt < submitted_dt):
        include_new = False
        if not executor_alive and submitted_dt and open_refreshed_dt:
            try:
                include_new = (open_refreshed_dt - submitted_dt).total_seconds() >= 5
            except Exception:
                include_new = False
        sync_trade_orders_from_open_orders(
            session,
            open_orders_payload,
            mode=run.mode,
            run_id=run.id,
            include_new=include_new,
            run_executor_active=executor_alive,
        )
    # Finalize CANCEL_REQUESTED orders when a cancel worker already processed the request.
    from app.services.trade_cancel import reconcile_cancel_requested_orders

    reconcile_cancel_requested_orders(session, run_id=run.id)
    positions_payload = read_positions(_resolve_bridge_root())
    reconcile_run_with_positions(session, run, positions_payload, open_tags=open_tags)
    now = datetime.utcnow()
    pending_summary = _collect_timed_out_submit_pending_orders(
        session,
        run,
        now=now,
        timeout_seconds=_SUBMIT_COMMAND_PENDING_STALLED_SECONDS,
    )
    if pending_summary["timed_out"] > 0 and active_status in {"running", "stalled"}:
        params = dict(run.params or {})
        lean_exec = params.get("lean_execution") if isinstance(params.get("lean_execution"), dict) else {}
        if isinstance(lean_exec, dict) and str(lean_exec.get("source") or "").strip() == "leader_command":
            fallback_meta = params.get("leader_submit_runtime_fallback")
            fallback_triggered = isinstance(fallback_meta, dict) and bool(fallback_meta.get("triggered"))
            if not fallback_triggered:
                if _launch_short_lived_fallback_for_leader_submit(
                    session,
                    run,
                    reason="leader_submit_pending_timeout",
                    now=now,
                ):
                    record_audit(
                        session,
                        action="trade_run.leader_submit_fallback",
                        resource_type="trade_run",
                        resource_id=run.id,
                        detail={
                            "reason": "leader_submit_pending_timeout",
                            "timed_out": int(pending_summary["timed_out"]),
                            "pending": int(pending_summary["pending"]),
                            "oldest_age_seconds": round(float(pending_summary["oldest_age_seconds"] or 0.0), 3),
                            "orders": pending_summary["orders"][:20],
                        },
                    )
                    return True

        if active_status != "running":
            return False

        run.status = "stalled"
        run.stalled_at = now
        run.stalled_reason = "submit_command_pending_timeout"
        run.updated_at = now
        if not run.message or run.message in {"submitted_lean", "submitted_leader"}:
            run.message = "stalled"
        params = dict(run.params or {})
        checked_at = now.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        params["submit_command_pending_timeout"] = {
            "threshold_seconds": _SUBMIT_COMMAND_PENDING_STALLED_SECONDS,
            "timed_out": int(pending_summary["timed_out"]),
            "pending": int(pending_summary["pending"]),
            "oldest_age_seconds": round(float(pending_summary["oldest_age_seconds"] or 0.0), 3),
            "orders": pending_summary["orders"][:20],
            "checked_at": checked_at,
        }
        run.params = params
        session.commit()
        record_audit(
            session,
            action="trade_run.stalled",
            resource_type="trade_run",
            resource_id=run.id,
            detail={
                "stage": run.progress_stage,
                "last_progress_at": run.last_progress_at.isoformat() if run.last_progress_at else None,
                "reason": run.stalled_reason,
                "submit_command_pending_timeout": params["submit_command_pending_timeout"],
            },
        )
        return True
    if active_status == "stalled":
        params = dict(run.params or {})
        fallback_meta = params.get("leader_submit_runtime_fallback")
        lean_exec = params.get("lean_execution")
        fallback_triggered = isinstance(fallback_meta, dict) and bool(fallback_meta.get("triggered"))
        lean_source = ""
        if isinstance(lean_exec, dict):
            lean_source = str(lean_exec.get("source") or "").strip().lower()
        if (
            fallback_triggered
            and lean_source == "short_lived_fallback"
            and str(run.stalled_reason or "").strip().lower() == "submit_command_pending_timeout"
            and int(pending_summary["timed_out"] or 0) <= 0
        ):
            resumed_at = now
            if resumed_at.tzinfo is None:
                resumed_at = resumed_at.replace(tzinfo=timezone.utc)
            else:
                resumed_at = resumed_at.astimezone(timezone.utc)
            cleared_pending = _clear_leader_submit_pending_after_fallback(
                session,
                run,
                resolved_at=resumed_at,
                reason="fallback_auto_resume",
            )
            fallback_payload = dict(fallback_meta)
            fallback_payload["auto_resumed_at"] = resumed_at.isoformat().replace("+00:00", "Z")
            previous_cleared = 0
            try:
                previous_cleared = int(fallback_payload.get("cleared_pending_orders") or 0)
            except (TypeError, ValueError):
                previous_cleared = 0
            fallback_payload["cleared_pending_orders"] = max(0, previous_cleared) + int(cleared_pending)
            params["leader_submit_runtime_fallback"] = fallback_payload
            params.pop("submit_command_pending_timeout", None)
            run.params = params
            run.status = "running"
            run.stalled_at = None
            run.stalled_reason = None
            run.updated_at = now
            run.message = "submitted_lean_fallback"
            session.commit()
            update_trade_run_progress(session, run, "submitted_lean_fallback", reason="fallback_auto_resume", commit=True)
            return True
    if _lean_submit_blocked_during_warmup(run.id):
        now = datetime.utcnow()
        reason = "submit_during_warmup"
        rejected = 0
        cancelled = 0
        filled = 0
        update_trade_run_progress(session, run, "order_rejected", reason=reason, commit=True)
        for order in (
            session.query(TradeOrder)
            .filter(TradeOrder.run_id == run.id)
            .order_by(TradeOrder.id.asc())
            .all()
        ):
            status = str(order.status or "").strip().upper()
            if status == "FILLED":
                filled += 1
                continue
            if status in _REJECTED_ORDER_STATUSES:
                rejected += 1
                continue
            if status in _CANCELLED_ORDER_STATUSES:
                existing_params = order.params if isinstance(order.params, dict) else {}
                sync_reason = str(existing_params.get("sync_reason") or "").strip().lower()
                low_conf_cancel = (
                    sync_reason == "missing_from_open_orders"
                    and order.ib_order_id is None
                    and order.ib_perm_id is None
                )
                if low_conf_cancel:
                    params_payload = dict(existing_params)
                    params_payload.update(
                        {
                            "event_source": "lean_runtime",
                            "event_status": "REJECTED",
                            "event_reason": reason,
                            "sync_reason": "lean_runtime_error",
                            "runtime_error": "order_request_submit_blocked_during_warmup",
                            "runtime_superseded_from_status": status,
                        }
                    )
                    rejected_reason = "OrderRequest.Submit blocked during warmup/initialize"
                    payload = {
                        "status": "REJECTED",
                        "rejected_reason": rejected_reason,
                        "params": params_payload,
                    }
                    try:
                        force_update_trade_order_status(session, order, payload, commit=False)
                    except ValueError:
                        cancelled += 1
                        continue
                    rejected += 1
                    continue
                cancelled += 1
                continue
            params_payload = {
                "event_source": "lean_runtime",
                "event_status": "REJECTED",
                "event_reason": reason,
                "sync_reason": "lean_runtime_error",
                "runtime_error": "order_request_submit_blocked_during_warmup",
            }
            rejected_reason = "OrderRequest.Submit blocked during warmup/initialize"
            payload = {
                "status": "REJECTED",
                "rejected_reason": rejected_reason,
                "params": params_payload,
            }
            try:
                force_update_trade_order_status(session, order, payload, commit=False)
            except ValueError:
                continue
            rejected += 1

        params = dict(run.params or {})
        lean_exec = params.get("lean_execution") if isinstance(params.get("lean_execution"), dict) else {}
        pid = lean_exec.get("pid") if isinstance(lean_exec, dict) else None
        source = str(lean_exec.get("source") or "").strip().lower() if isinstance(lean_exec, dict) else ""
        output_dir = str(lean_exec.get("output_dir") or "").strip() if isinstance(lean_exec, dict) else ""
        if pid and source != "leader_command":
            if not output_dir or output_dir != str(bridge_root):
                _terminate_pid(pid, force=False)
                if _pid_alive(pid):
                    _terminate_pid(pid, force=True)
                if not _pid_alive(pid):
                    now_iso = now.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                    lean_exec["pid"] = None
                    lean_exec["terminated_at"] = now_iso
                    lean_exec["terminated_reason"] = reason
                    params["lean_execution"] = lean_exec

        params["completion_summary"] = {
            "filled": filled,
            "cancelled": cancelled,
            "rejected": rejected,
            "skipped": 0,
            "runtime_error": "order_request_submit_blocked_during_warmup",
        }
        params["lean_submit_blocked_during_warmup"] = {
            "detected_at": now.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            "reason": reason,
        }
        run.params = params
        run.status = "failed"
        run.message = "execution_error:submit_during_warmup"
        run.ended_at = now
        run.updated_at = now
        run.stalled_at = None
        run.stalled_reason = None
        session.commit()
        record_audit(
            session,
            action="trade_run.runtime_error",
            resource_type="trade_run",
            resource_id=run.id,
            detail={
                "reason": reason,
                "rejected": rejected,
                "cancelled": cancelled,
                "filled": filled,
            },
        )
        return True

    if _lean_no_orders_submitted(run.id):
        cancelled = 0
        filled = 0
        held_symbols: list[str] = []
        positions_map = _build_positions_map(positions_payload)
        baseline = _load_positions_baseline(run)
        if not baseline and positions_map:
            # When Lean exits with "no orders submitted", it implies positions didn't change.
            # If we don't have a pre-run baseline (older runs/tests), treat current holdings as baseline
            # for the purpose of detecting already-held targets.
            baseline = {symbol: float(item.get("quantity") or 0.0) for symbol, item in positions_map.items()}
        update_trade_run_progress(session, run, "no_orders_submitted", reason="lean_execution", commit=True)
        for order in (
            session.query(TradeOrder)
            .filter(TradeOrder.run_id == run.id)
            .order_by(TradeOrder.id.asc())
            .all()
        ):
            status = str(order.status or "").strip().upper()
            if isinstance(order.params, dict) and order.params.get("already_held") is True:
                symbol = str(order.symbol or "").strip().upper()
                if symbol:
                    held_symbols.append(symbol)
            if status in {"NEW", "SUBMITTED", "PARTIAL", "CANCEL_REQUESTED"}:
                symbol_key = str(order.symbol or "").strip().upper()
                side = str(order.side or "").strip().upper()
                base_qty = float(baseline.get(symbol_key, 0.0))
                qty = float(order.quantity or 0.0)
                if side == "BUY" and qty > 0 and base_qty >= qty - 1e-6:
                    fill_price = None
                    pos = positions_map.get(symbol_key) or {}
                    avg_cost = pos.get("avg_cost")
                    if avg_cost is not None:
                        try:
                            avg_cost_value = float(avg_cost)
                        except (TypeError, ValueError):
                            avg_cost_value = None
                        if avg_cost_value is not None and avg_cost_value > 0:
                            fill_price = float(avg_cost_value)
                    if fill_price is None:
                        fallback = order.avg_fill_price or order.limit_price
                        if fallback is not None:
                            try:
                                fallback_value = float(fallback)
                            except (TypeError, ValueError):
                                fallback_value = None
                            if fallback_value is not None and fallback_value > 0:
                                fill_price = float(fallback_value)
                    try:
                        if status == "NEW":
                            update_trade_order_status(
                                session,
                                order,
                                {"status": "SUBMITTED", "params": {"already_held": True}},
                            )
                        update_trade_order_status(
                            session,
                            order,
                            {
                                "status": "FILLED",
                                "filled_quantity": qty,
                                "avg_fill_price": fill_price,
                                "params": {"already_held": True},
                            },
                        )
                    except ValueError:
                        pass
                    else:
                        filled += 1
                        if symbol_key:
                            held_symbols.append(symbol_key)
                        continue
                try:
                    update_trade_order_status(
                        session,
                        order,
                        {"status": "CANCELED", "params": {"cancel_reason": "no_orders_submitted"}},
                    )
                except ValueError:
                    continue
                cancelled += 1
        run.status = "failed"
        run.message = "no_orders_submitted"
        run.ended_at = now
        run.updated_at = now
        run.stalled_at = None
        run.stalled_reason = None
        params = dict(run.params or {})
        params["completion_summary"] = {
            "filled": filled,
            "cancelled": cancelled,
            "rejected": 0,
            "skipped": 0,
            "no_orders_submitted": True,
        }
        params["no_orders_submitted"] = True
        if held_symbols:
            params["already_held_orders"] = sorted(set(held_symbols))
        run.params = params
        session.commit()
        record_audit(
            session,
            action="trade_run.no_orders_submitted",
            resource_type="trade_run",
            resource_id=run.id,
            detail={"cancelled": cancelled},
        )
        return True
    statuses = [
        row[0]
        for row in session.query(TradeOrder.status).filter(TradeOrder.run_id == run.id).all()
    ]
    status, summary = determine_run_status(statuses)
    if status is None:
        if active_status != "running":
            return False
        now = datetime.utcnow()
        trading_open = is_market_open(now)
        if not is_trade_run_stalled(
            run,
            now,
            window_minutes=_STALLED_WINDOW_MINUTES,
            trading_open=trading_open,
        ):
            return False
        run.status = "stalled"
        run.stalled_at = now
        run.stalled_reason = f"no_progress_{_STALLED_WINDOW_MINUTES}m"
        run.updated_at = now
        if not run.message or run.message in {"submitted_lean", "submitted_leader"}:
            run.message = "stalled"
        record_audit(
            session,
            action="trade_run.stalled",
            resource_type="trade_run",
            resource_id=run.id,
            detail={
                "stage": run.progress_stage,
                "last_progress_at": run.last_progress_at.isoformat() if run.last_progress_at else None,
                "reason": run.stalled_reason,
            },
        )
        return True
    run.status = status
    run.ended_at = datetime.utcnow()
    run.updated_at = datetime.utcnow()
    run.stalled_at = None
    run.stalled_reason = None
    params = dict(run.params or {})
    params["completion_summary"] = summary
    run.params = params
    if not run.message or run.message in {"submitted_lean", "submitted_leader"}:
        run.message = "orders_complete"
    return True


def _read_decision_items(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    file_path = Path(path)
    if not file_path.exists():
        return []
    try:
        with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows: list[dict[str, Any]] = []
            for row in csv.DictReader(handle):
                symbol = (row.get("symbol") or "").strip().upper()
                if not symbol:
                    continue
                rows.append(
                    {
                        "symbol": symbol,
                        "weight": row.get("weight"),
                    }
                )
            return rows
    except OSError:
        return []


def _build_client_order_id(run_id: int, snapshot_id: int | None, symbol: str, side: str) -> str:
    base = f"{run_id}:{symbol}:{side}"
    if snapshot_id:
        return f"{base}:{snapshot_id}"
    return base


def _merge_risk_params(defaults: dict[str, Any] | None, overrides: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if isinstance(defaults, dict):
        merged.update(defaults)
    if isinstance(overrides, dict):
        merged.update(overrides)
    return merged


def execute_trade_run(
    run_id: int,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> TradeExecutionResult:
    session = SessionLocal()
    lock = None
    if not dry_run:
        lock = JobLock("trade_execution", Path(settings.data_root) if settings.data_root else None)
        if not lock.acquire():
            session.close()
            raise RuntimeError("trade_execution_lock_busy")
    run: TradeRun | None = None
    try:
        run = session.get(TradeRun, run_id)
        if not run:
            raise RuntimeError("trade_run_not_found")
        if run.status not in {"queued", "blocked", "failed"}:
            raise RuntimeError("trade_run_status_invalid")
        if run.status != "queued" and not force:
            raise RuntimeError("trade_run_not_queued")

        guard_state = get_or_create_guard_state(
            session,
            project_id=run.project_id,
            mode=run.mode,
        )
        if guard_state.status == "halted" and not force:
            run.status = "blocked"
            run.message = "guard_halted"
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
            notify_trade_alert(session, f"Trade run blocked: guard halted (run={run.id})")
            return TradeExecutionResult(
                run_id=run.id,
                status=run.status,
                filled=0,
                cancelled=0,
                rejected=0,
                skipped=0,
                message=run.message,
                dry_run=dry_run,
            )

        settings_row = session.query(TradeSettings).order_by(TradeSettings.id.desc()).first()
        execution_source = (settings_row.execution_data_source if settings_row else "lean") or "lean"
        skip_build = _should_skip_order_build(execution_source)
        if execution_source.lower() != "lean":
            params = dict(run.params or {})
            params["execution_data_source"] = execution_source
            params["expected_execution_data_source"] = "lean"
            run.status = "blocked"
            run.message = "execution_data_source_mismatch"
            run.params = dict(params)
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
            return TradeExecutionResult(
                run_id=run.id,
                status=run.status,
                filled=0,
                cancelled=0,
                rejected=0,
                skipped=0,
                message=run.message,
                dry_run=dry_run,
            )

        if not _bridge_connection_ok():
            run.status = "blocked"
            run.message = "bridge_unavailable"
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
            notify_trade_alert(session, f"Trade run blocked: lean bridge unavailable (run={run.id})")
            return TradeExecutionResult(
                run_id=run.id,
                status=run.status,
                filled=0,
                cancelled=0,
                rejected=0,
                skipped=0,
                message=run.message,
                dry_run=dry_run,
            )

        orders = (
            session.query(TradeOrder)
            .filter(TradeOrder.run_id == run.id)
            .order_by(TradeOrder.id.asc())
            .all()
        )
        price_map: dict[str, float] = {}
        params = dict(run.params or {})
        if not orders:
            if run.decision_snapshot_id is None:
                run.status = "blocked"
                run.message = "decision_snapshot_required"
                run.ended_at = datetime.utcnow()
                run.updated_at = datetime.utcnow()
                session.commit()
                return TradeExecutionResult(
                    run_id=run.id,
                    status=run.status,
                    filled=0,
                    cancelled=0,
                    rejected=0,
                    skipped=0,
                    message=run.message,
                    dry_run=dry_run,
                )
            snapshot = session.get(DecisionSnapshot, run.decision_snapshot_id)
            if snapshot is None or not snapshot.items_path:
                run.status = "failed"
                run.message = "decision_snapshot_items_missing"
                run.ended_at = datetime.utcnow()
                session.commit()
                return TradeExecutionResult(
                    run_id=run.id,
                    status=run.status,
                    filled=0,
                    cancelled=0,
                    rejected=0,
                    skipped=0,
                    message=run.message,
                    dry_run=dry_run,
                )
            items = _read_decision_items(snapshot.items_path)
            if not items:
                run.status = "failed"
                run.message = "decision_snapshot_items_empty"
                run.ended_at = datetime.utcnow()
                session.commit()
                return TradeExecutionResult(
                    run_id=run.id,
                    status=run.status,
                    filled=0,
                    cancelled=0,
                    rejected=0,
                    skipped=0,
                    message=run.message,
                    dry_run=dry_run,
                )

            # Build a SetHoldings-style rebalance plan:
            # - size targets from snapshot weights
            # - compare against *current* positions
            # - emit delta BUY/SELL orders
            positions_payload = read_positions(_resolve_bridge_root())
            positions_map = _build_positions_map(positions_payload)
            current_positions: dict[str, float] = {
                symbol: float(meta.get("quantity") or 0.0) for symbol, meta in positions_map.items()
            }

            target_weights: dict[str, float] = {}
            for item in items:
                symbol = str(item.get("symbol") or "").strip().upper()
                if not symbol:
                    continue
                try:
                    weight_value = float(item.get("weight") or 0.0)
                except (TypeError, ValueError):
                    continue
                target_weights[symbol] = float(weight_value)

            held_symbols = {
                symbol
                for symbol, qty in current_positions.items()
                if symbol and abs(float(qty or 0.0)) > 1e-9
            }
            symbols = sorted(set(target_weights.keys()) | held_symbols)
            price_map = _build_price_map(symbols)

            now = datetime.utcnow()
            session_value = str(
                params.get("session")
                or params.get("execution_session")
                or params.get("trading_session")
                or ""
            ).strip().lower()
            allow_outside = params.get("allow_outside_rth")
            if allow_outside is None:
                allow_outside = params.get("outside_rth")
            extended = {
                "pre",
                "premarket",
                "pre_market",
                "post",
                "after",
                "afterhours",
                "after_hours",
                "night",
                "overnight",
            }
            if allow_outside is None and session_value:
                allow_outside = session_value in extended
            if not session_value or allow_outside is None:
                inferred_session, inferred_outside = _infer_auto_session(now)
                if not session_value:
                    session_value = inferred_session
                if allow_outside is None:
                    allow_outside = inferred_outside

            order_type_raw = params.get("order_type")
            if order_type_raw:
                order_type = validate_order_type(order_type_raw)
            else:
                order_type = "ADAPTIVE_LMT" if session_value == "rth" else "LMT"
            params["order_type"] = order_type
            params.setdefault("execution_session", session_value)
            params.setdefault("allow_outside_rth", bool(allow_outside))

            # Always prefer latest NetLiquidation from Lean bridge for sizing. Keeping an older
            # portfolio_value in run.params would drift target_qty and break delta sizing.
            account_summary = fetch_account_summary(session)
            if isinstance(account_summary, dict):
                net_liq = account_summary.get("NetLiquidation")
                if net_liq is not None:
                    try:
                        portfolio_value = float(net_liq)
                    except (TypeError, ValueError):
                        portfolio_value = 0.0
                    if portfolio_value > 0:
                        params["portfolio_value"] = portfolio_value
                cash_available = account_summary.get("cash_available")
                if cash_available is not None:
                    params.setdefault("cash_available", cash_available)
            try:
                portfolio_value = float(params.get("portfolio_value") or 0.0)
            except (TypeError, ValueError):
                portfolio_value = 0.0
            if portfolio_value <= 0:
                run.status = "failed"
                run.message = "portfolio_value_required"
                run.ended_at = datetime.utcnow()
                run.params = dict(params)
                run.updated_at = datetime.utcnow()
                session.commit()
                return TradeExecutionResult(
                    run_id=run.id,
                    status=run.status,
                    filled=0,
                    cancelled=0,
                    rejected=0,
                    skipped=0,
                    message=run.message,
                    dry_run=dry_run,
                )

            cash_buffer_ratio = float(params.get("cash_buffer_ratio") or 0.0)
            lot_size = int(params.get("lot_size") or 1)
            min_qty = int(params.get("min_qty") or 1)

            # Delta rebalance orders (BUY/SELL) compiled from target weights vs current positions.
            rebalance_orders = build_rebalance_orders(
                target_weights=target_weights,
                current_positions=current_positions,
                price_map=price_map,
                portfolio_value=portfolio_value,
                cash_buffer_ratio=cash_buffer_ratio,
                lot_size=lot_size,
                min_qty=min_qty,
                order_type=order_type,
            )
            if not rebalance_orders:
                # No trades needed, treat this run as a no-op success.
                now = datetime.utcnow()
                run.status = "done"
                run.message = "no_orders_required"
                run.ended_at = now
                run.updated_at = now
                params = dict(params)
                params["completion_summary"] = {
                    "total": 0,
                    "filled": 0,
                    "cancelled": 0,
                    "rejected": 0,
                    "skipped": 0,
                    "no_orders_required": True,
                }
                run.params = params
                session.commit()
                return TradeExecutionResult(
                    run_id=run.id,
                    status=run.status,
                    filled=0,
                    cancelled=0,
                    rejected=0,
                    skipped=0,
                    message=run.message,
                    dry_run=dry_run,
                )

            # Prefer sells first so buys have cash headroom.
            rebalance_orders = sorted(
                rebalance_orders,
                key=lambda item: (
                    1 if str(item.get("side") or "").strip().upper() == "BUY" else 0,
                    str(item.get("symbol") or "").strip().upper(),
                ),
            )

            trade_symbols = [str(item.get("symbol") or "").strip().upper() for item in rebalance_orders]
            trade_symbol_set = set(trade_symbols)
            side_map: dict[str, str] = {
                str(item.get("symbol") or "").strip().upper(): str(item.get("side") or "").strip().upper()
                for item in rebalance_orders
                if item.get("symbol")
            }
            limit_price_map: dict[str, float] | None = None
            if is_limit_like(order_type):
                limit_price_map = _build_limit_price_map(
                    trade_symbols,
                    side_map=side_map,
                    order_type=order_type,
                    fallback_prices=price_map,
                )
            prime_price_map: dict[str, float] | None = None
            if validate_order_type(order_type) == "ADAPTIVE_LMT":
                # Adaptive LMT itself should not carry explicit limit price to TWS.
                # We still persist a priming price for Lean-side SecurityPriceZero protection.
                prime_price_map = {
                    symbol: float(price)
                    for symbol, price in price_map.items()
                    if symbol in trade_symbol_set and price is not None and float(price) > 0
                }

            intent_items: list[dict[str, Any]] = []
            draft_orders: list[dict[str, Any]] = []
            for idx, draft in enumerate(rebalance_orders, start=1):
                symbol = str(draft.get("symbol") or "").strip().upper()
                side = str(draft.get("side") or "").strip().upper()
                if not symbol or side not in {"BUY", "SELL"}:
                    continue
                qty_value = float(draft.get("quantity") or 0.0)
                if qty_value <= 0:
                    continue
                intent_id = f"oi_{run.id}_{idx}"
                limit_price_value = None
                if limit_price_map is not None:
                    limit_price_value = limit_price_map.get(symbol)
                if limit_price_value is None and is_limit_like(order_type):
                    # Ensure order creation passes validation even when limit-price builder
                    # fails to emit a per-symbol price (fallback to latest known price).
                    fallback_price = price_map.get(symbol)
                    if fallback_price is not None and float(fallback_price) > 0:
                        limit_price_value = float(fallback_price)
                draft_orders.append(
                    {
                        "client_order_id": intent_id,
                        "symbol": symbol,
                        "side": side,
                        "quantity": qty_value,
                        "order_type": validate_order_type(order_type),
                        "limit_price": limit_price_value,
                    }
                )
                signed_qty = qty_value if side == "BUY" else -qty_value
                intent_items.append(
                    {
                        "order_intent_id": intent_id,
                        "symbol": symbol,
                        "quantity": signed_qty,
                        "weight": float(draft.get("target_weight") or 0.0),
                        "order_type": validate_order_type(order_type),
                        "limit_price": limit_price_value,
                        "outside_rth": bool(allow_outside),
                        "session": session_value,
                    }
                )

            if not draft_orders:
                run.status = "failed"
                run.message = "orders_empty"
                run.ended_at = datetime.utcnow()
                session.commit()
                return TradeExecutionResult(
                    run_id=run.id,
                    status=run.status,
                    filled=0,
                    cancelled=0,
                    rejected=0,
                    skipped=0,
                    message=run.message,
                    dry_run=dry_run,
                )

            intent_path = write_order_intent(
                session,
                snapshot_id=run.decision_snapshot_id,
                items=intent_items,
                output_dir=ARTIFACT_ROOT / "order_intents",
                run_id=run.id,
                order_type=order_type,
                limit_price_map=limit_price_map,
                prime_price_map=prime_price_map,
                outside_rth=bool(allow_outside),
                execution_session=session_value,
            )
            params["order_intent_path"] = intent_path
            auto_recovery_defaults = {
                # NEW status recovery (backend-side)
                "new_timeout_seconds": 45,
                "max_auto_retries": 1,
                "max_price_deviation_pct": 1.5,
                "allow_replace_outside_rth": False,
                # SUBMITTED/PARTIAL long-unfilled handling (Lean-side)
                "unfilled_timeout_seconds": 600,
                "unfilled_reprice_interval_seconds": 0,
                "unfilled_max_reprices": 0,
                "unfilled_max_price_deviation_pct": 1.5,
            }
            auto_recovery_effective = dict(auto_recovery_defaults)
            if settings_row and isinstance(settings_row.auto_recovery, dict):
                auto_recovery_effective.update(settings_row.auto_recovery)
            # Optional per-run overrides (advanced use)
            if isinstance(params.get("auto_recovery"), dict):
                auto_recovery_effective.update(params["auto_recovery"])
            execution_params = {
                "min_qty": int(params.get("min_qty") or 1),
                "lot_size": int(params.get("lot_size") or 1),
                "cash_buffer_ratio": float(params.get("cash_buffer_ratio") or 0.0),
                "fee_bps": float(params.get("fee_bps") or 0.0),
                "slippage_open_bps": float(params.get("slippage_open_bps") or 0.0),
                "slippage_close_bps": float(params.get("slippage_close_bps") or 0.0),
                "risk_overrides": params.get("risk_overrides") or {},
                # Long-unfilled policy for LeanBridgeExecutionAlgorithm
                "unfilled_timeout_seconds": int(auto_recovery_effective.get("unfilled_timeout_seconds") or 0),
                "unfilled_reprice_interval_seconds": int(
                    auto_recovery_effective.get("unfilled_reprice_interval_seconds") or 0
                ),
                "unfilled_max_reprices": int(auto_recovery_effective.get("unfilled_max_reprices") or 0),
                "unfilled_max_price_deviation_pct": float(
                    auto_recovery_effective.get("unfilled_max_price_deviation_pct")
                    or auto_recovery_effective.get("max_price_deviation_pct")
                    or 0.0
                ),
            }
            params["execution_params_path"] = write_execution_params(
                output_dir=ARTIFACT_ROOT / "order_intents",
                run_id=run.id,
                params=execution_params,
            )

            created = 0
            for draft in draft_orders:
                payload = dict(draft)
                payload["params"] = {
                    "source": "decision_snapshot",
                    "decision_snapshot_id": run.decision_snapshot_id,
                    "client_order_id_auto": True,
                    "order_intent_id": payload.get("client_order_id"),
                    "intent_only": True,
                }
                result = create_trade_order(session, payload, run_id=run.id)
                if result.created:
                    created += 1
            session.commit()
            orders = (
                session.query(TradeOrder)
                .filter(TradeOrder.run_id == run.id)
                .order_by(TradeOrder.id.asc())
                .all()
            )
            params["builder"] = {
                "mode": "rebalance_delta",
                "portfolio_value": portfolio_value,
                "cash_buffer_ratio": cash_buffer_ratio,
                "lot_size": lot_size,
                "order_type": validate_order_type(order_type),
                "min_qty": min_qty,
                "created_orders": created,
                "target_symbols": len(target_weights),
                "held_symbols": len(held_symbols),
            }
            params["price_map"] = price_map
            run.params = dict(params)
            run.updated_at = datetime.utcnow()
            session.commit()

        intent_path = params.get("order_intent_path")
        if intent_path:
            if not enforce_intent_order_match(session, run, orders, intent_path):
                return TradeExecutionResult(
                    run_id=run.id,
                    status=run.status,
                    filled=0,
                    cancelled=0,
                    rejected=0,
                    skipped=0,
                    message=run.message,
                    dry_run=dry_run,
                )

        if not price_map:
            symbols = sorted({order.symbol for order in orders})
            price_map = _build_price_map(symbols)

        defaults = settings_row.risk_defaults if settings_row else {}
        risk_overrides: dict[str, Any] = {}
        # Backward-compat: older runs stored risk overrides under `params.risk`.
        if isinstance(params.get("risk"), dict):
            risk_overrides.update(params.get("risk") or {})
        if isinstance(params.get("risk_overrides"), dict):
            # Explicit key wins over legacy `risk`.
            risk_overrides.update(params.get("risk_overrides") or {})
        risk_params = _merge_risk_params(defaults, risk_overrides)
        account_summary = fetch_account_summary(session)
        if isinstance(account_summary, dict):
            net_liq = account_summary.get("NetLiquidation")
            if net_liq is not None and not params.get("portfolio_value"):
                try:
                    portfolio_value = float(net_liq)
                except (TypeError, ValueError):
                    portfolio_value = 0.0
                if portfolio_value > 0:
                    params["portfolio_value"] = portfolio_value
                    run.params = dict(params)
                    run.updated_at = datetime.utcnow()
                    session.commit()
            cash_available = account_summary.get("cash_available")
            if cash_available is not None and "cash_available" not in risk_params:
                risk_params["cash_available"] = cash_available
            params.setdefault("cash_available", cash_available)
        params["risk_effective"] = risk_params
        max_order_notional = risk_params.get("max_order_notional")
        max_position_ratio = risk_params.get("max_position_ratio")
        max_total_notional = risk_params.get("max_total_notional")
        max_symbols = risk_params.get("max_symbols")
        min_cash_buffer_ratio = risk_params.get("min_cash_buffer_ratio")
        cash_available = risk_params.get("cash_available") or params.get("cash_available")
        portfolio_value = risk_params.get("portfolio_value") or params.get("portfolio_value")

        risk_bypass = bool(params.get("risk_bypass"))
        if not risk_bypass:
            intent_path = params.get("order_intent_path")
            cash_buffer_ratio = float(params.get("cash_buffer_ratio") or 0.0)
            lot_size = int(params.get("lot_size") or 1)
            min_qty = int(params.get("min_qty") or 1)
            notional_limits_enabled = any(
                value is not None
                for value in (
                    max_order_notional,
                    max_position_ratio,
                    max_total_notional,
                )
            )
            if skip_build and intent_path:
                # In lean execution mode, orders may be created as "intent only" drafts with
                # quantity=0. This breaks notional-based risk checks. We size the draft orders
                # from intent weights when portfolio_value and prices are available.
                needs_sizing = any(float(order.quantity or 0.0) <= 0 for order in orders)
                pv_value = None
                if portfolio_value not in (None, ""):
                    try:
                        pv_value = float(portfolio_value)
                    except (TypeError, ValueError):
                        pv_value = None
                if needs_sizing and notional_limits_enabled and (pv_value is None or pv_value <= 0):
                    run.status = "blocked"
                    run.message = "risk_portfolio_value_required"
                    params["risk_blocked"] = {
                        "reasons": ["risk_portfolio_value_required"],
                        "count": len(orders),
                        "risk_effective": risk_params,
                    }
                    run.params = dict(params)
                    run.ended_at = datetime.utcnow()
                    run.updated_at = datetime.utcnow()
                    session.commit()
                    return TradeExecutionResult(
                        run_id=run.id,
                        status=run.status,
                        filled=0,
                        cancelled=0,
                        rejected=0,
                        skipped=0,
                        message=run.message,
                        dry_run=dry_run,
                    )
                if needs_sizing and pv_value and pv_value > 0:
                    size_map = _build_sized_qty_map_from_intent(
                        intent_path,
                        price_map=price_map,
                        portfolio_value=pv_value,
                        cash_buffer_ratio=cash_buffer_ratio,
                        lot_size=lot_size,
                        min_qty=min_qty,
                    )
                    sized = 0
                    missing: list[str] = []
                    for order in orders:
                        if float(order.quantity or 0.0) > 0:
                            continue
                        symbol = str(order.symbol or "").strip().upper()
                        side = str(order.side or "").strip().upper()
                        if not symbol or not side:
                            continue
                        qty_value = size_map.get((symbol, side))
                        if qty_value is None:
                            missing.append(symbol)
                            continue
                        order.quantity = float(qty_value)
                        sized += 1
                    if sized:
                        session.commit()
                    if notional_limits_enabled and any(float(order.quantity or 0.0) <= 0 for order in orders):
                        run.status = "blocked"
                        run.message = "risk_sizing_incomplete"
                        params["risk_blocked"] = {
                            "reasons": ["risk_sizing_incomplete"],
                            "count": len(orders),
                            "missing_symbols": sorted(set(missing))[:50],
                            "risk_effective": risk_params,
                        }
                        run.params = dict(params)
                        run.ended_at = datetime.utcnow()
                        run.updated_at = datetime.utcnow()
                        session.commit()
                        return TradeExecutionResult(
                            run_id=run.id,
                            status=run.status,
                            filled=0,
                            cancelled=0,
                            rejected=0,
                            skipped=0,
                            message=run.message,
                            dry_run=dry_run,
                        )

            risk_orders = []
            for order in orders:
                price = price_map.get(order.symbol)
                risk_orders.append(
                    {
                        "symbol": order.symbol,
                        "side": order.side,
                        "quantity": order.quantity,
                        "price": price or 0.0,
                    }
                )
            ok, blocked_orders, reasons = evaluate_orders(
                risk_orders,
                max_order_notional=max_order_notional,
                max_position_ratio=max_position_ratio,
                portfolio_value=portfolio_value,
                max_total_notional=max_total_notional,
                max_symbols=max_symbols,
                cash_available=cash_available,
                min_cash_buffer_ratio=min_cash_buffer_ratio,
            )
            if not ok:
                run.status = "blocked"
                run.message = reasons[0] if reasons else "risk_blocked"
                params["risk_blocked"] = {
                    "reasons": reasons,
                    "count": len(blocked_orders),
                    "risk_effective": risk_params,
                }
                run.params = dict(params)
                run.ended_at = datetime.utcnow()
                run.updated_at = datetime.utcnow()
                session.commit()
                return TradeExecutionResult(
                    run_id=run.id,
                    status=run.status,
                    filled=0,
                    cancelled=0,
                    rejected=0,
                    skipped=0,
                    message=run.message,
                    dry_run=dry_run,
                )
        else:
            run.params = dict(params)
            run.updated_at = datetime.utcnow()
            session.commit()

        run.status = "running"
        run.started_at = datetime.utcnow()
        run.updated_at = datetime.utcnow()
        session.commit()
        update_trade_run_progress(session, run, "run_started", reason="execution_start", commit=True)

        filled = 0
        cancelled = 0
        rejected = 0
        skipped = 0
        if dry_run:
            run.status = "done"
            run.message = "dry_run"
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
            return TradeExecutionResult(
                run_id=run.id,
                status=run.status,
                filled=filled,
                cancelled=cancelled,
                rejected=rejected,
                skipped=skipped,
                message=run.message,
                dry_run=dry_run,
            )

        intent_path = params.get("order_intent_path")
        if not intent_path:
            run.status = "failed"
            run.message = "order_intent_missing"
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
            return TradeExecutionResult(
                run_id=run.id,
                status=run.status,
                filled=filled,
                cancelled=cancelled,
                rejected=rejected,
                skipped=skipped,
                message=run.message,
                dry_run=dry_run,
            )
        ensure_order_intent_ids(intent_path, snapshot_id=run.decision_snapshot_id)

        if not params.get("execution_params_path"):
            auto_recovery_defaults = {
                # NEW status recovery (backend-side)
                "new_timeout_seconds": 45,
                "max_auto_retries": 1,
                "max_price_deviation_pct": 1.5,
                "allow_replace_outside_rth": False,
                # SUBMITTED/PARTIAL long-unfilled handling (Lean-side)
                "unfilled_timeout_seconds": 600,
                "unfilled_reprice_interval_seconds": 0,
                "unfilled_max_reprices": 0,
                "unfilled_max_price_deviation_pct": 1.5,
            }
            auto_recovery_effective = dict(auto_recovery_defaults)
            if settings_row and isinstance(settings_row.auto_recovery, dict):
                auto_recovery_effective.update(settings_row.auto_recovery)
            # Optional per-run overrides (advanced use)
            if isinstance(params.get("auto_recovery"), dict):
                auto_recovery_effective.update(params["auto_recovery"])

            execution_params = {
                "min_qty": int(params.get("min_qty") or 1),
                "lot_size": int(params.get("lot_size") or 1),
                "cash_buffer_ratio": float(params.get("cash_buffer_ratio") or 0.0),
                "fee_bps": float(params.get("fee_bps") or 0.0),
                "slippage_open_bps": float(params.get("slippage_open_bps") or 0.0),
                "slippage_close_bps": float(params.get("slippage_close_bps") or 0.0),
                "risk_overrides": params.get("risk_overrides") or {},
                # Long-unfilled policy for LeanBridgeExecutionAlgorithm
                "unfilled_timeout_seconds": int(auto_recovery_effective.get("unfilled_timeout_seconds") or 0),
                "unfilled_reprice_interval_seconds": int(
                    auto_recovery_effective.get("unfilled_reprice_interval_seconds") or 0
                ),
                "unfilled_max_reprices": int(auto_recovery_effective.get("unfilled_max_reprices") or 0),
                "unfilled_max_price_deviation_pct": float(
                    auto_recovery_effective.get("unfilled_max_price_deviation_pct")
                    or auto_recovery_effective.get("max_price_deviation_pct")
                    or 0.0
                ),
            }
            params["execution_params_path"] = write_execution_params(
                output_dir=ARTIFACT_ROOT / "order_intents",
                run_id=run.id,
                params=execution_params,
            )
            run.params = dict(params)
            run.updated_at = datetime.utcnow()
            session.commit()

        # Record a pre-run positions baseline so holdings-based reconciliation can infer fills
        # without treating already-held positions as executed orders.
        if not params.get("positions_baseline"):
            symbols = sorted({str(order.symbol or "").strip().upper() for order in orders if order.symbol})
            positions_payload = read_positions(_resolve_bridge_root())
            if isinstance(positions_payload, dict) and positions_payload.get("stale") is not True and symbols:
                pos_map = _build_positions_map(positions_payload)
                baseline_items = []
                for symbol in symbols:
                    try:
                        qty = float((pos_map.get(symbol) or {}).get("quantity") or 0.0)
                    except (TypeError, ValueError):
                        qty = 0.0
                    baseline_items.append({"symbol": symbol, "quantity": qty})
                params["positions_baseline"] = {
                    "refreshed_at": positions_payload.get("refreshed_at") or positions_payload.get("updated_at"),
                    "items": baseline_items,
                }
                run.params = dict(params)
                run.updated_at = datetime.utcnow()
                session.commit()

        bridge_root = _resolve_bridge_root()
        prefer_leader_submit = _should_use_leader_submit(params, orders)
        if prefer_leader_submit and _is_bridge_ready_for_submit(bridge_root):
            leader_submit = _submit_run_orders_via_leader(
                session,
                run=run,
                orders=orders,
                params=params,
                bridge_root=bridge_root,
            )
            params.setdefault("lean_execution", {})
            if isinstance(params.get("lean_execution"), dict):
                params["lean_execution"].update(leader_submit)
            run.params = dict(params)
            run.updated_at = datetime.utcnow()
            session.commit()
            run.status = "running"
            run.message = "submitted_leader"
            run.updated_at = datetime.utcnow()
            session.commit()
            update_trade_run_progress(session, run, "submitted_leader", reason="leader_command", commit=True)

            return TradeExecutionResult(
                run_id=run.id,
                status=run.status,
                filled=filled,
                cancelled=cancelled,
                rejected=rejected,
                skipped=skipped,
                message=run.message,
                dry_run=dry_run,
            )
        if prefer_leader_submit:
            fallback_reason = _leader_submit_fallback_reason(bridge_root)
            params["leader_submit_fallback"] = {
                "reason": fallback_reason,
                "checked_at": datetime.utcnow().isoformat() + "Z",
            }
            run.params = dict(params)
            run.updated_at = datetime.utcnow()
            session.commit()

        exec_output_dir = ARTIFACT_ROOT / "lean_bridge_runs" / f"run_{run.id}"
        config = build_execution_config(
            intent_path=intent_path,
            brokerage="InteractiveBrokersBrokerage",
            project_id=run.project_id,
            mode=run.mode,
            params_path=params.get("execution_params_path"),
            lean_bridge_output_dir=str(exec_output_dir),
        )
        _apply_unfilled_management_launch_config(
            config,
            params_path=params.get("execution_params_path"),
        )
        config_dir = ARTIFACT_ROOT / "lean_execution"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"trade_run_{run.id}.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        pid = launch_execution_async(config_path=str(config_path))
        params.setdefault("lean_execution", {})
        if isinstance(params.get("lean_execution"), dict):
            params["lean_execution"].update(
                {
                    "config_path": str(config_path),
                    "pid": pid,
                    "output_dir": str(exec_output_dir),
                    "submitted_at": datetime.utcnow().isoformat() + "Z",
                }
            )
        run.params = dict(params)
        run.updated_at = datetime.utcnow()
        session.commit()
        run.status = "running"
        run.message = "submitted_lean"
        run.updated_at = datetime.utcnow()
        session.commit()
        update_trade_run_progress(session, run, "submitted_lean", reason="lean_execution", commit=True)

        return TradeExecutionResult(
            run_id=run.id,
            status=run.status,
            filled=filled,
            cancelled=cancelled,
            rejected=rejected,
            skipped=skipped,
            message=run.message,
            dry_run=dry_run,
        )
    except Exception as exc:
        if run is not None:
            run.status = "failed"
            run.message = f"execution_error:{exc}"
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
        raise
    finally:
        if lock is not None:
            lock.release()
        session.close()
