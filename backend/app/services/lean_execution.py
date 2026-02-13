from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
import subprocess
import os
from pathlib import Path
from dataclasses import dataclass

from sqlalchemy import func

from app.core.config import settings
from app.db import SessionLocal
from app.models import TradeFill, TradeOrder, TradeRun
from app.services.ib_settings import derive_client_id
from app.services.trade_orders import (
    create_trade_order,
    force_update_trade_order_status,
    update_trade_order_status,
)

subprocess_run = subprocess.run

_DEFAULT_LAUNCHER_DIR = Path("/app/stocklean/Lean_git/Launcher/bin/Release")
_DEFAULT_CONFIG_TEMPLATE = Path("/app/stocklean/configs/lean_live_interactive_paper.json")

@dataclass
class _JsonlIngestState:
    offset: int = 0
    tail: str = ""


# In-process cache to avoid re-reading large jsonl files on every poll.
# Safe for correctness: events are idempotent; restart resets the cache.
_JSONL_INGEST_STATE: dict[str, _JsonlIngestState] = {}
_JSONL_INITIAL_REPLAY_MAX_BYTES = max(
    int(getattr(settings, "lean_jsonl_initial_replay_max_bytes", 8 * 1024 * 1024) or 8 * 1024 * 1024),
    256 * 1024,
)
_SUBMITTED_RECOVERY_EVENT_MAX_AGE_SECONDS = max(
    int(getattr(settings, "lean_submitted_recovery_event_max_age_seconds", 900) or 900),
    30,
)
_SUBMITTED_RECOVERY_EVENT_CLOCK_SKEW_SECONDS = 5


def _bridge_output_dir() -> str:
    base = settings.data_root or "/data/share/stock/data"
    return str(Path(base) / "lean_bridge")


def _resolve_template_path() -> Path | None:
    if settings.lean_config_template:
        path = Path(settings.lean_config_template)
        if path.exists():
            return path
    if _DEFAULT_CONFIG_TEMPLATE.exists():
        return _DEFAULT_CONFIG_TEMPLATE
    return None


def _load_template_config() -> dict:
    base: dict = {}
    path = _resolve_template_path()
    if path:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            base.update(payload)

    if _DEFAULT_CONFIG_TEMPLATE.exists():
        try:
            fallback = json.loads(_DEFAULT_CONFIG_TEMPLATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            fallback = {}
        if isinstance(fallback, dict):
            for key, value in fallback.items():
                if key not in base:
                    base[key] = value
                    continue
                existing = base.get(key)
                if existing in (None, "", [], {}):
                    base[key] = value

    return base


def _resolve_environment(brokerage: str, mode: str) -> str:
    if str(brokerage or "").lower() == "interactivebrokersbrokerage":
        return "live-interactive"
    return "live"


def build_execution_config(
    *,
    intent_path: str,
    brokerage: str,
    project_id: int,
    mode: str,
    client_id: int | None = None,
    params_path: str | None = None,
    lean_bridge_output_dir: str | None = None,
) -> dict:
    payload = dict(_load_template_config())
    payload["environment"] = _resolve_environment(brokerage, mode)
    payload["algorithm-type-name"] = "LeanBridgeExecutionAlgorithm"
    # Prevent Lean console launcher from blocking on "Press any key to continue." after completion.
    payload["close-automatically"] = True
    if payload.get("algorithm-type-name") in {"LeanBridgeExecutionAlgorithm", "LeanBridgeSmokeAlgorithm"}:
        payload["algorithm-language"] = "CSharp"
    payload.setdefault("data-folder", "/data/share/stock/data/lean")
    payload["brokerage"] = brokerage
    payload["execution-intent-path"] = intent_path
    if params_path:
        payload["execution-params-path"] = params_path
    payload["result-handler"] = "QuantConnect.Lean.Engine.Results.LeanBridgeResultHandler"
    output_dir = lean_bridge_output_dir or _bridge_output_dir()
    payload["lean-bridge-output-dir"] = output_dir
    payload["lean-bridge-watchlist-path"] = str(Path(output_dir) / "watchlist.json")
    payload["lean-bridge-watchlist-refresh-seconds"] = "5"
    # Enable per-execution command processing (e.g. manual cancels). Commands live under the
    # execution output-dir so only the matching ib-client-id connection processes them.
    payload.setdefault("lean-bridge-commands-enabled", True)
    payload.setdefault("lean-bridge-commands-seconds", "1")
    payload.setdefault("lean-bridge-commands-dir", str(Path(output_dir) / "commands"))
    _write_watchlist_from_intent(intent_path, payload["lean-bridge-watchlist-path"])
    payload["ib-client-id"] = int(client_id) if client_id is not None else derive_client_id(
        project_id=project_id, mode=mode
    )
    return payload


def _write_watchlist_from_intent(intent_path: str, watchlist_path: str) -> None:
    intent_file = Path(intent_path)
    if not intent_file.exists():
        return

    try:
        items = json.loads(intent_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    if not isinstance(items, list):
        return

    symbols: list[str] = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)

    if not symbols:
        return

    watchlist_file = Path(watchlist_path)
    watchlist_file.parent.mkdir(parents=True, exist_ok=True)
    watchlist_file.write_text(json.dumps(symbols, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_launcher() -> tuple[str, str | None]:
    dll_setting = str(settings.lean_launcher_dll or "").strip()
    launcher_path = str(settings.lean_launcher_path or "").strip()

    launcher_dir: Path | None = None
    if launcher_path:
        launcher_candidate = Path(launcher_path)
        if launcher_candidate.exists() and launcher_candidate.is_file():
            launcher_dir = launcher_candidate.parent
        else:
            launcher_dir = launcher_candidate

    if dll_setting:
        dll_path = Path(dll_setting)
        if not dll_path.is_absolute() and launcher_dir is not None:
            dll_path = launcher_dir / dll_path
        cwd = str(dll_path.parent) if dll_path.is_absolute() else (str(launcher_dir) if launcher_dir is not None else None)
        return str(dll_path), cwd

    if launcher_dir is not None:
        dll_path = launcher_dir / "QuantConnect.Lean.Launcher.dll"
        if not dll_path.exists():
            candidate = launcher_dir / "bin" / "Release" / "QuantConnect.Lean.Launcher.dll"
            if candidate.exists():
                return str(candidate), str(candidate.parent)
        return str(dll_path), str(launcher_dir)

    dll_path = _DEFAULT_LAUNCHER_DIR / "QuantConnect.Lean.Launcher.dll"
    return str(dll_path), str(_DEFAULT_LAUNCHER_DIR)


def _build_launch_env() -> dict[str, str]:
    env = os.environ.copy()
    if settings.dotnet_root:
        env["DOTNET_ROOT"] = settings.dotnet_root
        env["PATH"] = f"{settings.dotnet_root}:{env.get('PATH', '')}"
    if settings.python_dll:
        env["PYTHONNET_PYDLL"] = settings.python_dll
    if settings.lean_python_venv:
        env["PYTHONHOME"] = settings.lean_python_venv
    return env


def launch_execution(*, config_path: str) -> None:
    dll_path, cwd = _resolve_launcher()
    cmd = [settings.dotnet_path or "dotnet", dll_path, "--config", config_path]
    subprocess_run(cmd, check=False, cwd=cwd, env=_build_launch_env())

def launch_execution_async(*, config_path: str) -> int:
    dll_path, cwd = _resolve_launcher()
    cmd = [settings.dotnet_path or "dotnet", dll_path, "--config", config_path]
    proc = subprocess.Popen(cmd, cwd=cwd, env=_build_launch_env())
    return int(proc.pid)


def _read_jsonl_events_incremental(path: Path, *, skip_existing_on_first_read: bool = False) -> list[dict]:
    key = str(path)
    state = _JSONL_INGEST_STATE.get(key)
    if state is None:
        state = _JsonlIngestState()
        _JSONL_INGEST_STATE[key] = state
    try:
        size = path.stat().st_size
    except OSError:
        state.offset = 0
        state.tail = ""
        return []

    # For long-lived global event streams, replaying the full backlog after process restart can
    # block API requests for minutes. Allow callers to start from EOF on first read and only
    # process newly appended events.
    if skip_existing_on_first_read and state.offset == 0 and size > 0:
        state.offset = size
        state.tail = ""
        return []

    # Hard guardrail: if caller does request first-read replay on a very large stream, only scan
    # the recent tail to keep request latency bounded. Historical events are already persisted in
    # DB and fresh state converges via later incremental reads/open-orders reconciliation.
    if not skip_existing_on_first_read and state.offset == 0 and size > _JSONL_INITIAL_REPLAY_MAX_BYTES:
        state.offset = max(0, size - _JSONL_INITIAL_REPLAY_MAX_BYTES)

    if size < state.offset:
        # File was truncated or rotated; start over.
        state.offset = 0
        state.tail = ""

    try:
        with path.open("rb") as handle:
            handle.seek(state.offset)
            data = handle.read()
    except OSError:
        return []

    state.offset = size
    text = data.decode("utf-8", errors="ignore")
    if state.tail:
        text = state.tail + text
        state.tail = ""

    if not text.strip():
        return []

    events: list[dict] = []
    lines = text.splitlines()
    if not lines:
        return events

    ends_with_newline = text.endswith("\n") or text.endswith("\r")
    last_index = len(lines) - 1
    for idx, line in enumerate(lines):
        raw = line.strip()
        if not raw:
            continue
        if idx == last_index and not ends_with_newline:
            # Last line may be partially written; only process it if it's valid JSON.
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                state.tail = raw
                continue
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue

        if isinstance(parsed, dict):
            events.append(parsed)
        elif isinstance(parsed, list):
            events.extend([item for item in parsed if isinstance(item, dict)])

    return events


def _parse_run_id_from_event_path(path_value: object) -> int | None:
    text = str(path_value or "").strip()
    if not text:
        return None
    normalized = text.replace("\\", "/")
    marker = "/run_"
    idx = normalized.rfind(marker)
    if idx < 0:
        return None
    tail = normalized[idx + len(marker) :]
    if "/" not in tail:
        return None
    run_part, rest = tail.split("/", 1)
    if rest != "execution_events.jsonl":
        return None
    try:
        return int(run_part)
    except (TypeError, ValueError):
        return None


def _is_trusted_run_scoped_no_exec_fill(*, intent_id: str, event_path: object) -> bool:
    intent_run_id = _parse_intent_run_id(intent_id)
    if intent_run_id is None:
        return False
    path_run_id = _parse_run_id_from_event_path(event_path)
    if path_run_id is None:
        return False
    return int(intent_run_id) == int(path_run_id)


def ingest_execution_events(
    path: str,
    *,
    session=None,
    skip_existing_on_first_read: bool = False,
) -> dict:
    file_path = Path(path)
    if file_path.suffix.lower() == ".jsonl":
        events = _read_jsonl_events_incremental(
            file_path,
            skip_existing_on_first_read=bool(skip_existing_on_first_read),
        )
    else:
        content = file_path.read_text(encoding="utf-8")
        try:
            parsed = json.loads(content)
            # A single-line jsonl file is valid JSON (dict). Treat it as one event.
            if isinstance(parsed, list):
                events = parsed
            elif isinstance(parsed, dict):
                events = [parsed]
            else:
                events = []
        except json.JSONDecodeError:
            events = []
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    event_path = str(file_path)
    normalized_events: list[dict] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if "_event_path" in event:
            normalized_events.append(event)
            continue
        enriched = dict(event)
        enriched["_event_path"] = event_path
        normalized_events.append(enriched)

    if session is None:
        return apply_execution_events(normalized_events)
    return apply_execution_events(normalized_events, session=session)


def _parse_event_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = value.replace("Z", "+00:00")
    if "." in text:
        head, tail = text.split(".", 1)
        tz = ""
        tz_index = None
        for sep in ("+", "-"):
            idx = tail.find(sep)
            if idx > 0:
                tz_index = idx
                break
        if tz_index is not None:
            frac = tail[:tz_index]
            tz = tail[tz_index:]
        else:
            frac = tail
        if len(frac) > 6:
            frac = frac[:6]
        text = f"{head}.{frac}{tz}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_event_time_optional(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    if "." in normalized:
        head, tail = normalized.split(".", 1)
        tz = ""
        tz_index = None
        for sep in ("+", "-"):
            idx = tail.find(sep)
            if idx > 0:
                tz_index = idx
                break
        if tz_index is not None:
            frac = tail[:tz_index]
            tz = tail[tz_index:]
        else:
            frac = tail
        if len(frac) > 6:
            frac = frac[:6]
        normalized = f"{head}.{frac}{tz}"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_utc(value: datetime | None) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _can_recover_low_conf_submitted_event(order: TradeOrder, event_time: str | None) -> bool:
    parsed_event_time = _parse_event_time_optional(event_time)
    if parsed_event_time is None:
        return False
    now = datetime.now(timezone.utc)
    try:
        age_seconds = (now - parsed_event_time).total_seconds()
    except Exception:
        return False
    if age_seconds < -_SUBMITTED_RECOVERY_EVENT_CLOCK_SKEW_SECONDS:
        return False
    if age_seconds > _SUBMITTED_RECOVERY_EVENT_MAX_AGE_SECONDS:
        return False
    updated_at = _to_utc(getattr(order, "updated_at", None))
    if updated_at is not None:
        if parsed_event_time + timedelta(seconds=_SUBMITTED_RECOVERY_EVENT_CLOCK_SKEW_SECONDS) < updated_at:
            return False
    return True


def _apply_fill_to_order(
    session,
    order: TradeOrder,
    *,
    fill_qty: float,
    fill_price: float,
    fill_time: datetime,
    exec_id: str | None = None,
) -> TradeFill | None:
    if not exec_id:
        exec_id = f"lean:{order.id}:{int(fill_time.timestamp() * 1000)}"
    fill_qty_abs = abs(float(fill_qty))
    if fill_qty_abs <= 0:
        raise ValueError("invalid_fill_quantity")
    fill_price_value = float(fill_price)

    def _is_synthetic(value: str | None) -> bool:
        text = str(value or "")
        return (
            text.startswith("lean:")
            or text.startswith("lean_direct:")
            or text.startswith("positions_reconcile:")
            or text.startswith("positions_reconcile_direct:")
        )

    def _is_positions_reconcile(value: str | None) -> bool:
        text = str(value or "")
        return text.startswith("positions_reconcile:") or text.startswith("positions_reconcile_direct:")

    incoming_synthetic = _is_synthetic(exec_id)

    def _same_fill_signature(candidate: TradeFill) -> bool:
        try:
            candidate_qty = abs(float(candidate.fill_quantity or 0.0))
            candidate_price = float(candidate.fill_price or 0.0)
        except (TypeError, ValueError):
            return False
        if abs(candidate_qty - fill_qty_abs) > 1e-9:
            return False
        if abs(candidate_price - fill_price_value) > 1e-6:
            return False
        candidate_time = candidate.fill_time
        if candidate_time is None:
            return True
        if candidate_time.tzinfo is None:
            candidate_time = candidate_time.replace(tzinfo=timezone.utc)
        target_time = fill_time if fill_time.tzinfo is not None else fill_time.replace(tzinfo=timezone.utc)
        return abs((candidate_time - target_time).total_seconds()) <= 2.0

    def _sync_order_from_recorded_fills() -> None:
        persisted = (
            session.query(
                func.coalesce(func.sum(TradeFill.fill_quantity), 0.0),
                func.coalesce(func.sum(TradeFill.fill_quantity * TradeFill.fill_price), 0.0),
            )
            .filter(TradeFill.order_id == order.id)
            .one()
        )
        persisted_qty = abs(float(persisted[0] or 0.0))
        weighted_value = float(persisted[1] or 0.0)
        pending_fills = [
            pending
            for pending in session.new
            if isinstance(pending, TradeFill) and pending.order_id == order.id
        ]
        if pending_fills:
            persisted_qty += sum(abs(float(p.fill_quantity or 0.0)) for p in pending_fills)
            weighted_value += sum(
                abs(float(p.fill_quantity or 0.0)) * float(p.fill_price or 0.0) for p in pending_fills
            )

        if persisted_qty <= 0:
            return
        avg_value = weighted_value / persisted_qty if persisted_qty > 0 else float(order.avg_fill_price or 0.0)
        quantity_target = abs(float(order.quantity or 0.0))
        target_status = "PARTIAL" if quantity_target > 0 and persisted_qty < quantity_target else "FILLED"
        update_payload = {
            "status": target_status,
            "filled_quantity": persisted_qty,
            "avg_fill_price": avg_value,
        }
        try:
            update_trade_order_status(session, order, update_payload, commit=False)
        except ValueError as exc:
            if str(exc).startswith("invalid_transition:"):
                force_update_trade_order_status(session, order, update_payload, commit=False)
            else:
                raise

    # Session autoflush is disabled for this app's SessionLocal, so ensure we don't
    # create duplicates within one ingestion pass by checking pending instances.
    for pending in session.new:
        if not isinstance(pending, TradeFill) or pending.order_id != order.id:
            continue
        if pending.exec_id == exec_id:
            _sync_order_from_recorded_fills()
            return pending
        if (incoming_synthetic or _is_synthetic(pending.exec_id)) and _same_fill_signature(pending):
            _sync_order_from_recorded_fills()
            return pending
    existing = (
        session.query(TradeFill)
        .filter(TradeFill.order_id == order.id, TradeFill.exec_id == exec_id)
        .first()
    )
    if existing:
        _sync_order_from_recorded_fills()
        return existing

    existing_fills = session.query(TradeFill).filter(TradeFill.order_id == order.id).all()
    for candidate in existing_fills:
        if candidate.exec_id == exec_id:
            _sync_order_from_recorded_fills()
            return candidate
        if not (incoming_synthetic or _is_synthetic(candidate.exec_id)):
            continue
        if _same_fill_signature(candidate):
            _sync_order_from_recorded_fills()
            return candidate

    # When positions-based reconciliation emitted a synthetic fill first and IB execution
    # details arrive later, prefer upgrading the reconciliation fill to real exec metadata
    # instead of double-counting quantity.
    if not incoming_synthetic:
        for candidate in existing_fills:
            if not _is_positions_reconcile(candidate.exec_id):
                continue
            try:
                candidate_qty = abs(float(candidate.fill_quantity or 0.0))
            except (TypeError, ValueError):
                continue
            if abs(candidate_qty - fill_qty_abs) > 1e-9:
                continue
            candidate_time = candidate.fill_time
            if candidate_time is not None:
                if candidate_time.tzinfo is None:
                    candidate_time = candidate_time.replace(tzinfo=timezone.utc)
                target_time = fill_time if fill_time.tzinfo is not None else fill_time.replace(tzinfo=timezone.utc)
                if abs((candidate_time - target_time).total_seconds()) > 300.0:
                    continue
            candidate.exec_id = exec_id
            candidate.fill_price = fill_price_value
            candidate.fill_time = fill_time
            merged_params = dict(candidate.params or {})
            merged_params.update({"source": "lean_bridge", "reconciled_from": "positions_reconcile"})
            candidate.params = merged_params
            _sync_order_from_recorded_fills()
            return candidate

    current_status = str(order.status or "").strip().upper()
    total_prev_raw = float(order.filled_quantity or 0.0)
    if total_prev_raw > 0:
        total_prev = total_prev_raw
    else:
        historical_total = (
            session.query(func.coalesce(func.sum(TradeFill.fill_quantity), 0.0))
            .filter(TradeFill.order_id == order.id)
            .scalar()
        )
        try:
            total_prev = float(historical_total or 0.0)
        except (TypeError, ValueError):
            total_prev = 0.0
        if total_prev < 0:
            total_prev = 0.0

    quantity_target = abs(float(order.quantity or 0.0))
    if quantity_target > 0 and total_prev >= quantity_target - 1e-9:
        _sync_order_from_recorded_fills()
        return None

    total_new = total_prev + fill_qty_abs
    if quantity_target > 0 and total_new > quantity_target:
        fill_qty_abs = quantity_target - total_prev
        if fill_qty_abs <= 1e-9:
            _sync_order_from_recorded_fills()
            return None
        total_new = quantity_target
    if total_new <= 0:
        total_new = fill_qty_abs

    avg_prev = float(order.avg_fill_price or 0.0)
    if total_prev <= 0:
        avg_new = fill_price_value
    else:
        avg_new = (avg_prev * total_prev + fill_price_value * fill_qty_abs) / total_new

    target_status = "PARTIAL" if quantity_target > 0 and total_new < quantity_target else "FILLED"
    if current_status == "NEW":
        update_trade_order_status(session, order, {"status": "SUBMITTED"}, commit=False)
    update_payload = {"status": target_status, "filled_quantity": total_new, "avg_fill_price": avg_new}
    try:
        update_trade_order_status(session, order, update_payload, commit=False)
    except ValueError as exc:
        # Fills can race with cancel events (or low-confidence open-orders inference). If we have a
        # concrete fill quantity/price, prefer the fill signal and reconcile the state machine.
        if str(exc).startswith("invalid_transition:"):
            force_update_trade_order_status(session, order, update_payload, commit=False)
        else:
            raise
    fill = TradeFill(
        order_id=order.id,
        exec_id=exec_id,
        fill_quantity=fill_qty_abs,
        fill_price=fill_price_value,
        commission=None,
        fill_time=fill_time,
        params={"source": "lean_bridge"},
    )
    session.add(fill)
    return fill


def _load_intent_items(path: str) -> list[dict]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _parse_intent_run_id(intent_id: str) -> int | None:
    if not intent_id:
        return None
    parts = str(intent_id).split("_")
    if len(parts) < 3 or parts[0] != "oi":
        return None
    try:
        return int(parts[1])
    except (TypeError, ValueError):
        return None


def _find_intent_for_id(session, intent_id: str) -> tuple[TradeRun | None, dict | None]:
    if not intent_id:
        return None, None
    run_id = _parse_intent_run_id(intent_id)
    if run_id:
        run = session.get(TradeRun, run_id)
        if run is not None:
            params = run.params or {}
            intent_path = params.get("order_intent_path")
            if intent_path:
                for item in _load_intent_items(intent_path):
                    if str(item.get("order_intent_id") or "").strip() == intent_id:
                        return run, item
    runs = session.query(TradeRun).all()
    for run in runs:
        params = run.params or {}
        intent_path = params.get("order_intent_path")
        if not intent_path:
            continue
        for item in _load_intent_items(intent_path):
            if str(item.get("order_intent_id") or "").strip() == intent_id:
                return run, item
    return None, None


def _merge_duplicate_order(session, *, target: TradeOrder, duplicate: TradeOrder) -> None:
    fills = session.query(TradeFill).filter(TradeFill.order_id == duplicate.id).all()
    for fill in fills:
        fill.order_id = target.id
    session.delete(duplicate)
    session.flush()


def _is_missing_from_open_orders_low_conf(order: TradeOrder, *, current_status: str | None = None) -> bool:
    status = str(current_status if current_status is not None else order.status or "").strip().upper()
    if status not in {"CANCELED", "CANCELLED", "SKIPPED"}:
        return False
    params = order.params if isinstance(order.params, dict) else {}
    return str(params.get("sync_reason") or "").strip() == "missing_from_open_orders"


def _apply_rejected_event_to_order(
    session,
    order: TradeOrder,
    *,
    current_status: str,
    event_params: dict[str, object],
    reason: object,
) -> bool:
    if current_status == "REJECTED":
        return True
    update_payload: dict[str, object] = {"status": "REJECTED", "params": dict(event_params)}
    if reason:
        update_payload["params"]["reason"] = str(reason)
        update_payload["rejected_reason"] = str(reason)
    recover_low_conf = _is_missing_from_open_orders_low_conf(order, current_status=current_status)
    if recover_low_conf:
        update_payload["params"]["sync_reason"] = "execution_event_rejected_recovered"
        update_payload["params"]["reconcile_recovered_from"] = current_status
    updater = force_update_trade_order_status if recover_low_conf else update_trade_order_status
    try:
        updater(session, order, update_payload, commit=False)
    except ValueError:
        return False
    return True


def _resolve_direct_or_manual_order_by_tag(session, tag: str) -> TradeOrder | None:
    normalized = str(tag or "").strip()
    if not normalized:
        return None

    order = (
        session.query(TradeOrder)
        .filter(TradeOrder.client_order_id == normalized)
        .order_by(TradeOrder.id.desc())
        .first()
    )
    if order is not None:
        return order

    # Fallback for historical inconsistent rows where event/client tags diverged.
    candidates = (
        session.query(TradeOrder)
        .filter(TradeOrder.run_id.is_(None))
        .order_by(TradeOrder.id.desc())
        .limit(4000)
        .all()
    )
    for candidate in candidates:
        params = candidate.params if isinstance(candidate.params, dict) else {}
        event_tag = str(params.get("event_tag") or "").strip()
        broker_tag = str(params.get("broker_order_tag") or "").strip()
        if normalized and (normalized == event_tag or normalized == broker_tag):
            return candidate
    return None


def _apply_event_to_existing_order(
    session,
    *,
    order: TradeOrder,
    event: dict,
    event_params: dict[str, object],
    status: str,
    filled_abs_value: float,
) -> bool:
    lean_order_id = event.get("order_id")
    if lean_order_id is not None and order.ib_order_id is None:
        try:
            order.ib_order_id = int(lean_order_id)
        except (TypeError, ValueError):
            pass

    if status in {"SUBMITTED", "NEW"}:
        current_status = str(order.status or "").strip().upper()
        if current_status in {"NEW", "SUBMITTED"}:
            try:
                update_trade_order_status(
                    session,
                    order,
                    {"status": "SUBMITTED", "params": event_params},
                    commit=False,
                )
            except ValueError:
                return False
        elif current_status in {"CANCELED", "CANCELLED", "SKIPPED"}:
            params = order.params or {}
            if (
                isinstance(params, dict)
                and params.get("sync_reason") == "missing_from_open_orders"
                and _can_recover_low_conf_submitted_event(order, str(event.get("time") or "").strip())
            ):
                recovered_params = dict(event_params)
                recovered_params["sync_reason"] = "execution_event_submitted_recovered"
                try:
                    force_update_trade_order_status(
                        session,
                        order,
                        {"status": "SUBMITTED", "params": recovered_params},
                        commit=False,
                    )
                except ValueError:
                    return False
        return True

    if status in {"CANCELPENDING", "PENDINGCANCEL", "CANCEL_REQUESTED"}:
        current_status = str(order.status or "").strip().upper()
        if current_status not in {"CANCEL_REQUESTED", "CANCELED", "CANCELLED", "REJECTED", "FILLED"}:
            try:
                update_trade_order_status(
                    session,
                    order,
                    {
                        "status": "CANCEL_REQUESTED",
                        "params": {
                            **event_params,
                            "event_status": "CANCEL_REQUESTED",
                            "sync_reason": "execution_cancel_pending",
                        },
                    },
                    commit=False,
                )
            except ValueError:
                return False
        return True

    if status in {"CANCELED", "CANCELLED"}:
        current_status = str(order.status or "").strip().upper()
        if current_status not in {"REJECTED", "FILLED"}:
            canceled_params = dict(event_params)
            canceled_params["sync_reason"] = "execution_event_canceled"
            try:
                update_trade_order_status(
                    session,
                    order,
                    {"status": "CANCELED", "params": canceled_params},
                    commit=False,
                )
            except ValueError:
                return False
        return True

    if status in {"REJECTED", "INVALID"}:
        current_status = str(order.status or "").strip().upper()
        reason = event.get("reason") or event.get("message")
        return _apply_rejected_event_to_order(
            session,
            order,
            current_status=current_status,
            event_params=event_params,
            reason=reason,
        )

    if status in {"FILLED", "PARTIALLYFILLED", "PARTIAL"} or filled_abs_value > 0:
        fill_qty = filled_abs_value
        if fill_qty <= 0:
            return False
        fill_price = float(event.get("fill_price") or 0.0)
        fill_time = _parse_event_time(event.get("time"))
        exec_id = event.get("exec_id") or f"lean_direct:{order.id}:{int(fill_time.timestamp() * 1000)}"
        try:
            _apply_fill_to_order(
                session,
                order,
                fill_qty=fill_qty,
                fill_price=fill_price,
                fill_time=fill_time,
                exec_id=exec_id,
            )
            filled_params = dict(event_params)
            filled_params["sync_reason"] = "execution_fill"
            try:
                update_trade_order_status(
                    session,
                    order,
                    {"status": str(order.status or "FILLED"), "params": filled_params},
                    commit=False,
                )
            except ValueError:
                pass
        except ValueError:
            return False
        return True

    return False


def apply_execution_events(events: list[dict], *, session=None) -> dict:
    own_session = False
    summary = {"processed": 0, "skipped_invalid_tag": 0, "skipped_not_found": 0}
    if session is None:
        session = SessionLocal()
        own_session = True
    try:
        for event in events or []:
            tag = str(event.get("tag") or "").strip()
            if not tag:
                summary["skipped_invalid_tag"] += 1
                continue
            event_path = str(event.get("_event_path") or "").strip()

            status = str(event.get("status") or "").strip().upper()
            filled_value = float(event.get("filled") or 0.0)
            filled_abs_value = abs(filled_value)
            event_time_iso = str(event.get("time") or "").strip()
            event_message = str(event.get("message") or "").strip()
            event_params = {
                "event_source": "lean",
                "event_tag": tag,
                "event_time": event_time_iso,
                "event_status": status,
            }
            if event_message:
                event_params["event_message"] = event_message

            # Direct order events use tag `direct:{trade_order_id}` and are stored under
            # `lean_bridge/direct_{trade_order_id}/execution_events.jsonl`.
            if tag.startswith("direct:"):
                raw = tag[len("direct:") :].strip()
                try:
                    order_id = int(raw)
                except ValueError:
                    summary["skipped_invalid_tag"] += 1
                    continue
                order = session.get(TradeOrder, order_id)
                if order is None:
                    summary["skipped_not_found"] += 1
                    continue
                if _apply_event_to_existing_order(
                    session,
                    order=order,
                    event=event,
                    event_params=event_params,
                    status=status,
                    filled_abs_value=filled_abs_value,
                ):
                    summary["processed"] += 1
                    continue
                summary["skipped_invalid_tag"] += 1
                continue

            if not tag.startswith("oi_"):
                order = _resolve_direct_or_manual_order_by_tag(session, tag)
                if order is None:
                    summary["skipped_not_found"] += 1
                    continue
                if _apply_event_to_existing_order(
                    session,
                    order=order,
                    event=event,
                    event_params=event_params,
                    status=status,
                    filled_abs_value=filled_abs_value,
                ):
                    summary["processed"] += 1
                    continue
                summary["skipped_invalid_tag"] += 1
                continue

            intent_id = tag
            run_id_hint = _parse_intent_run_id(intent_id)
            duplicate_order = None
            order = session.query(TradeOrder).filter(TradeOrder.client_order_id == intent_id).one_or_none()
            if order is not None and run_id_hint and order.run_id != run_id_hint:
                duplicate_order = order
                order = None

            if order is None:
                run, intent = _find_intent_for_id(session, intent_id)
                if run is None:
                    if duplicate_order is not None:
                        order = duplicate_order
                    else:
                        summary["skipped_not_found"] += 1
                        continue
                else:
                    symbol = (event.get("symbol") or intent.get("symbol") or "").strip().upper()
                    if not symbol:
                        summary["skipped_not_found"] += 1
                        continue
                    direction = str(event.get("direction") or "").strip().upper()
                    side = (
                        "BUY"
                        if direction in {"BUY", "LONG"}
                        else "SELL"
                        if direction in {"SELL", "SHORT"}
                        else ""
                    )
                    if not side:
                        summary["skipped_not_found"] += 1
                        continue

                    filled_qty = float(event.get("filled") or 0.0)
                    quantity = abs(filled_qty) if filled_qty else float(intent.get("quantity") or 0.0)
                    existing_orders = (
                        session.query(TradeOrder)
                        .filter(
                            TradeOrder.run_id == run.id,
                            TradeOrder.symbol == symbol,
                            TradeOrder.side == side,
                        )
                        .all()
                    )
                    matched = None
                    if existing_orders:
                        if quantity > 0:
                            for candidate in existing_orders:
                                if abs(float(candidate.quantity) - float(quantity)) < 1e-6:
                                    matched = candidate
                                    break
                        # For SUBMITTED events, filled quantity is 0 and intent drafts may omit quantity.
                        # In that case, fall back to symbol+side match when it is unambiguous.
                        if matched is None and len(existing_orders) == 1:
                            matched = existing_orders[0]
                    if matched is not None:
                        order = matched
                    else:
                        if quantity <= 0:
                            summary["skipped_not_found"] += 1
                            continue
                        payload = {
                            "client_order_id": intent_id,
                            "symbol": symbol,
                            "side": side,
                            "quantity": quantity,
                            "order_type": "MKT",
                            "params": {"source": "lean_bridge"},
                        }
                        result = create_trade_order(session, payload, run_id=run.id)
                        session.flush()
                        order = result.order

                    if duplicate_order is not None and order.id != duplicate_order.id:
                        _merge_duplicate_order(session, target=order, duplicate=duplicate_order)

            order_id = event.get("order_id")
            if order_id is not None and order.ib_order_id is None:
                try:
                    order.ib_order_id = int(order_id)
                except (TypeError, ValueError):
                    pass

            current_status = str(order.status or "").strip().upper()

            if status in {"SUBMITTED", "NEW"}:
                if current_status in {"NEW", "SUBMITTED"}:
                    try:
                        update_trade_order_status(
                            session,
                            order,
                            {"status": "SUBMITTED", "params": event_params},
                            commit=False,
                        )
                    except ValueError:
                        continue
                elif current_status in {"CANCELED", "CANCELLED", "SKIPPED"}:
                    params = order.params or {}
                    if (
                        isinstance(params, dict)
                        and params.get("sync_reason") == "missing_from_open_orders"
                        and _can_recover_low_conf_submitted_event(order, str(event.get("time") or "").strip())
                    ):
                        recovered_params = dict(event_params)
                        recovered_params["sync_reason"] = "execution_event_submitted_recovered"
                        try:
                            force_update_trade_order_status(
                                session,
                                order,
                                {"status": "SUBMITTED", "params": recovered_params},
                                commit=False,
                            )
                        except ValueError:
                            continue
                summary["processed"] += 1
                continue

            if status in {"CANCELPENDING", "PENDINGCANCEL", "CANCEL_REQUESTED"}:
                if current_status not in {"CANCEL_REQUESTED", "CANCELED", "CANCELLED", "REJECTED", "FILLED"}:
                    try:
                        update_trade_order_status(
                            session,
                            order,
                            {
                                "status": "CANCEL_REQUESTED",
                                "params": {
                                    **event_params,
                                    "event_status": "CANCEL_REQUESTED",
                                    "sync_reason": "execution_cancel_pending",
                                },
                            },
                            commit=False,
                        )
                    except ValueError:
                        continue
                summary["processed"] += 1
                continue

            if status in {"CANCELED", "CANCELLED"}:
                if current_status not in {"REJECTED", "FILLED"}:
                    canceled_params = dict(event_params)
                    canceled_params["sync_reason"] = "execution_event_canceled"
                    try:
                        update_trade_order_status(
                            session,
                            order,
                            {"status": "CANCELED", "params": canceled_params},
                            commit=False,
                        )
                    except ValueError:
                        continue
                summary["processed"] += 1
                continue

            if status in {"REJECTED", "INVALID"}:
                reason = event.get("reason") or event.get("message")
                if not _apply_rejected_event_to_order(
                    session,
                    order,
                    current_status=current_status,
                    event_params=event_params,
                    reason=reason,
                ):
                    continue
                summary["processed"] += 1
                continue

            if status in {"FILLED", "PARTIALLYFILLED", "PARTIAL"} or filled_abs_value > 0:
                filled_qty = filled_abs_value
                if filled_qty <= 0:
                    summary["skipped_not_found"] += 1
                    continue
                fill_price = float(event.get("fill_price") or 0.0)
                fill_time = _parse_event_time(event.get("time"))
                exec_id_raw = str(event.get("exec_id") or "").strip()
                if not exec_id_raw:
                    trusted_run_scoped_fill = _is_trusted_run_scoped_no_exec_fill(
                        intent_id=intent_id,
                        event_path=event_path,
                    )
                    if trusted_run_scoped_fill:
                        exec_id = (
                            f"lean_no_exec:{intent_id}:{int(fill_time.timestamp() * 1000)}:"
                            f"{int(round(filled_qty * 1_000_000))}"
                        )
                        try:
                            _apply_fill_to_order(
                                session,
                                order,
                                fill_qty=filled_qty,
                                fill_price=fill_price,
                                fill_time=fill_time,
                                exec_id=exec_id,
                            )
                            filled_params = dict(event_params)
                            filled_params["sync_reason"] = "execution_fill_no_exec_id_run_scoped"
                            filled_params["event_exec_id"] = "synthetic_no_exec_id"
                            try:
                                update_trade_order_status(
                                    session,
                                    order,
                                    {"status": str(order.status or "FILLED"), "params": filled_params},
                                    commit=False,
                                )
                            except ValueError:
                                pass
                        except ValueError:
                            continue
                        summary["processed"] += 1
                        continue

                    # Low-confidence event: without broker exec_id we have repeatedly observed
                    # false FILLED transitions under multi-executor IB client-id overlap.
                    # Keep the order active and wait for broker-backed fills (exec_id) or
                    # holdings reconciliation before terminalizing.
                    unconfirmed_params = dict(event_params)
                    unconfirmed_params["sync_reason"] = "execution_fill_unconfirmed_no_exec_id"
                    unconfirmed_params["reported_fill_quantity"] = float(filled_qty)
                    if fill_price > 0:
                        unconfirmed_params["reported_fill_price"] = float(fill_price)
                    target_status = current_status or "SUBMITTED"
                    if target_status == "NEW":
                        target_status = "SUBMITTED"
                    try:
                        update_trade_order_status(
                            session,
                            order,
                            {"status": target_status, "params": unconfirmed_params},
                            commit=False,
                        )
                    except ValueError:
                        try:
                            force_update_trade_order_status(
                                session,
                                order,
                                {"status": target_status, "params": unconfirmed_params},
                                commit=False,
                            )
                        except ValueError:
                            continue
                    summary["processed"] += 1
                    continue

                exec_id = exec_id_raw
                try:
                    _apply_fill_to_order(
                        session,
                        order,
                        fill_qty=filled_qty,
                        fill_price=fill_price,
                        fill_time=fill_time,
                        exec_id=exec_id,
                    )
                    # Preserve event metadata on the order for UI/debugging.
                    filled_params = dict(event_params)
                    filled_params["sync_reason"] = "execution_fill"
                    filled_params["event_exec_id"] = exec_id
                    try:
                        update_trade_order_status(
                            session,
                            order,
                            {"status": str(order.status or "FILLED"), "params": filled_params},
                            commit=False,
                        )
                    except ValueError:
                        pass
                except ValueError:
                    continue
                summary["processed"] += 1
                continue

            summary["skipped_invalid_tag"] += 1

        try:
            session.flush()
            session.commit()
        except Exception:
            session.rollback()
            raise
    finally:
        if own_session:
            session.close()
    return summary
