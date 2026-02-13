from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models import IBClientIdPool, TradeOrder, TradeRun
from app.services.audit_log import record_audit
from app.services.lean_bridge_commands import write_cancel_order_command
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_open_orders
from app.services.job_lock import JobLock
from app.services.ib_settings import derive_client_id, get_or_create_ib_settings
from app.services.lean_execution import launch_execution_async
from app.services.trade_orders import update_trade_order_status


_TERMINAL_ORDER_STATUSES = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "INVALID", "SKIPPED"}
_LOG = logging.getLogger(__name__)
_CANCEL_WORKER_TIMEOUT_SECONDS = 40
_CANCEL_RESULT_TERMINAL = {"ok", "not_found"}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_leader_submit_order(order: TradeOrder) -> bool:
    params = order.params if isinstance(order.params, dict) else {}
    submit = params.get("submit_command") if isinstance(params.get("submit_command"), dict) else {}
    source = str(submit.get("source") or "").strip().lower()
    if source == "leader_command":
        return True
    sync_reason = str(params.get("sync_reason") or "").strip().lower()
    if sync_reason.startswith("submit_command_"):
        return True
    command_path = str(submit.get("command_path") or "").strip()
    if command_path:
        command_parent = Path(command_path).parent
        if command_parent.name == "commands" and command_parent.parent == Path(resolve_bridge_root()):
            return True
    return False


def _candidate_result_roots(session, *, order: TradeOrder, meta: dict[str, Any]) -> list[Path]:
    roots: list[Path] = []

    output_dir = meta.get("output_dir")
    if isinstance(output_dir, str) and output_dir.strip():
        roots.append(Path(output_dir.strip()))

    try:
        roots.append(_resolve_order_output_dir(session, order=order))
    except Exception:
        pass

    params = order.params if isinstance(order.params, dict) else {}
    submit = params.get("submit_command") if isinstance(params.get("submit_command"), dict) else {}
    command_path = str(submit.get("command_path") or "").strip()
    if command_path:
        command_parent = Path(command_path).parent
        if command_parent.name == "commands":
            roots.append(command_parent.parent)

    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped


def reconcile_cancel_requested_orders(
    session,
    *,
    run_id: int | None = None,
    limit: int = 200,
    now: datetime | None = None,
) -> dict[str, int]:
    """Finalize CANCEL_REQUESTED orders based on Lean bridge command_results.

    When the original execution process already exited, a short-lived cancel worker (or leader)
    may execute the cancel and write `{output_dir}/command_results/{command_id}.json`.

    Without reconciling these results, orders can remain stuck in CANCEL_REQUESTED indefinitely.
    """

    summary = {"checked": 0, "updated": 0, "missing_result": 0, "skipped": 0}
    if session is None:
        return summary

    query = session.query(TradeOrder).filter(TradeOrder.status == "CANCEL_REQUESTED")
    if run_id is not None:
        query = query.filter(TradeOrder.run_id == int(run_id))
    orders = query.order_by(TradeOrder.id.asc()).limit(max(1, int(limit))).all()
    if not orders:
        return summary

    clock = now or datetime.now(timezone.utc)
    event_time_fallback = clock.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    for order in orders:
        summary["checked"] += 1
        params = order.params if isinstance(order.params, dict) else {}
        meta = params.get("user_cancel") if isinstance(params.get("user_cancel"), dict) else {}
        command_id = str(meta.get("command_id") or "").strip()
        if not command_id:
            summary["skipped"] += 1
            continue

        result_payload: dict[str, Any] | None = None
        result_path: Path | None = None
        for root in _candidate_result_roots(session, order=order, meta=meta):
            candidate = Path(root) / "command_results" / f"{command_id}.json"
            if not candidate.exists():
                continue
            payload = _read_json(candidate)
            if isinstance(payload, dict):
                result_payload = payload
                result_path = candidate
                break
        if result_payload is None or result_path is None:
            summary["missing_result"] += 1
            continue
        result_status = str(result_payload.get("status") or "").strip().lower()
        if result_status not in _CANCEL_RESULT_TERMINAL:
            summary["skipped"] += 1
            continue

        processed_at = str(result_payload.get("processed_at") or "").strip() or None
        event_time = processed_at or event_time_fallback
        sync_reason = f"cancel_command_{result_status}"
        try:
            update_trade_order_status(
                session,
                order,
                {
                    "status": "CANCELED",
                    "params": {
                        "event_source": "lean_command",
                        "event_status": "CANCELED",
                        "event_time": event_time,
                        "sync_reason": sync_reason,
                        "cancel_command": {
                            "command_id": command_id,
                            "result_status": result_status,
                            "processed_at": processed_at,
                            "result_path": str(result_path),
                            "brokerage_ids": result_payload.get("brokerage_ids"),
                        },
                        "user_cancel_completed": True,
                        "user_cancel_completed_at": event_time,
                    },
                },
            )
        except ValueError:
            summary["skipped"] += 1
            continue
        summary["updated"] += 1

    return summary


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _resolve_order_tag(order: TradeOrder) -> str:
    params = order.params if isinstance(order.params, dict) else {}
    broker_tag = str(params.get("broker_order_tag") or "").strip()
    if broker_tag:
        return broker_tag

    event_tag = str(params.get("event_tag") or "").strip()
    client_tag = str(order.client_order_id or "").strip()
    if event_tag:
        # Backward compatibility: historical direct/manual orders can keep `event_tag=direct:{id}`
        # even when IB/TWS broker tag is `client_order_id` (e.g. `oi_*` / `manual_*`).
        # In that case, prefer `client_order_id` for cancel command targeting.
        if client_tag and event_tag.startswith("direct:") and not client_tag.startswith("direct:"):
            return client_tag
        return event_tag
    return client_tag


def _open_orders_has_tag(open_orders_payload: dict[str, Any] | None, tag: str) -> bool:
    if not isinstance(open_orders_payload, dict) or open_orders_payload.get("stale") is True:
        return False
    items = open_orders_payload.get("items") if isinstance(open_orders_payload.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("tag") or "").strip() == tag:
            return True
    return False


def _resolve_run_output_dir(session, *, run_id: int) -> Path | None:
    run = session.get(TradeRun, int(run_id))
    if run is None:
        return None
    params = run.params if isinstance(run.params, dict) else {}
    lean_exec = params.get("lean_execution") if isinstance(params.get("lean_execution"), dict) else {}
    output_dir = lean_exec.get("output_dir")
    if isinstance(output_dir, str) and output_dir.strip():
        return Path(output_dir.strip())
    # Fallback to the default used by the executor when params are missing.
    artifact_root = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")
    return artifact_root / "lean_bridge_runs" / f"run_{int(run_id)}"


def _resolve_order_output_dir(session, *, order: TradeOrder) -> Path:
    if _is_leader_submit_order(order):
        return Path(resolve_bridge_root())
    if order.run_id is not None:
        resolved = _resolve_run_output_dir(session, run_id=int(order.run_id))
        if resolved is not None:
            return resolved
    bridge_root = resolve_bridge_root()
    return Path(bridge_root) / f"direct_{int(order.id)}"


def _resolve_execution_pid(session, *, order: TradeOrder) -> int | None:
    params = order.params if isinstance(order.params, dict) else {}

    manual = params.get("manual_execution") if isinstance(params.get("manual_execution"), dict) else {}
    try:
        pid = int(manual.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid > 0:
        return pid

    lease = session.query(IBClientIdPool).filter(IBClientIdPool.order_id == int(order.id)).first()
    if lease is not None and lease.pid:
        try:
            return int(lease.pid)
        except (TypeError, ValueError):
            return None

    if order.run_id is not None:
        run = session.get(TradeRun, int(order.run_id))
        if run is not None and isinstance(run.params, dict):
            lean_exec = run.params.get("lean_execution") if isinstance(run.params.get("lean_execution"), dict) else {}
            try:
                pid = int(lean_exec.get("pid") or 0)
            except (TypeError, ValueError):
                pid = 0
            if pid > 0:
                return pid

    return None


def _resolve_execution_config_path(session, *, order: TradeOrder) -> Path | None:
    params = order.params if isinstance(order.params, dict) else {}
    manual = params.get("manual_execution") if isinstance(params.get("manual_execution"), dict) else {}
    manual_config = manual.get("config_path")
    if isinstance(manual_config, str) and manual_config.strip():
        path = Path(manual_config.strip())
        if path.exists():
            return path

    if order.run_id is not None:
        run = session.get(TradeRun, int(order.run_id))
        if run is not None and isinstance(run.params, dict):
            lean_exec = run.params.get("lean_execution") if isinstance(run.params.get("lean_execution"), dict) else {}
            config_path = lean_exec.get("config_path")
            if isinstance(config_path, str) and config_path.strip():
                path = Path(config_path.strip())
                if path.exists():
                    return path

    artifact_root = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")
    candidate = artifact_root / "lean_execution" / f"direct_order_{int(order.id)}_config.json"
    if candidate.exists():
        return candidate
    candidate = artifact_root / "lean_execution" / f"manual_order_{int(order.id)}.json"
    if candidate.exists():
        return candidate
    return None


def _read_client_id_from_config(path: Path) -> int | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("ib-client-id")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _resolve_execution_client_id(session, *, order: TradeOrder) -> int | None:
    params = order.params if isinstance(order.params, dict) else {}
    raw = params.get("ib_client_id") or params.get("execution_client_id")
    if raw is not None:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = None
        else:
            if value >= 0:
                return value

    lease = session.query(IBClientIdPool).filter(IBClientIdPool.order_id == int(order.id)).first()
    if lease is not None and lease.client_id is not None:
        try:
            return int(lease.client_id)
        except (TypeError, ValueError):
            pass

    config_path = _resolve_execution_config_path(session, order=order)
    if config_path is not None:
        value = _read_client_id_from_config(config_path)
        if value is not None:
            return value

    if order.run_id is not None:
        run = session.get(TradeRun, int(order.run_id))
        if run is not None:
            return derive_client_id(project_id=int(run.project_id), mode=str(run.mode or "paper"))

    return None


def _resolve_execution_mode(session, *, order: TradeOrder) -> str:
    if order.run_id is not None:
        run = session.get(TradeRun, int(order.run_id))
        if run is not None and run.mode:
            return str(run.mode).strip().lower() or "paper"
    params = order.params if isinstance(order.params, dict) else {}
    return str(params.get("mode") or "paper").strip().lower() or "paper"


def _load_live_template_config() -> dict[str, Any]:
    base: dict[str, Any] = {}

    template = str(settings.lean_config_template or "").strip()
    if template:
        path = Path(template)
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                base.update(payload)

    def _merge_defaults(fallback: dict[str, Any]) -> None:
        for key, value in fallback.items():
            if key not in base:
                base[key] = value
                continue
            existing = base.get(key)
            if existing in (None, "", [], {}):
                base[key] = value

    for fallback_path in (
        Path("/app/stocklean/Lean_git/Launcher/config-lean-bridge-live-paper.json"),
        Path("/app/stocklean/configs/lean_live_interactive_paper.json"),
    ):
        if not fallback_path.exists():
            continue
        try:
            payload = json.loads(fallback_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            _merge_defaults(payload)

    return base


def _build_cancel_worker_config(
    session,
    *,
    mode: str,
    client_id: int,
    output_dir: Path,
    commands_dir: Path,
) -> dict[str, Any]:
    payload = dict(_load_live_template_config())
    settings_row = get_or_create_ib_settings(session)

    # Force live mode handlers (minimal requirements for LiveTradingResultHandler)
    payload["environment"] = "live-interactive"
    payload.setdefault("live-mode", True)
    payload.setdefault("live-mode-brokerage", "InteractiveBrokersBrokerage")
    payload["algorithm-type-name"] = "LeanBridgeSmokeAlgorithm"
    payload["algorithm-language"] = "CSharp"
    payload["brokerage"] = "InteractiveBrokersBrokerage"
    payload["result-handler"] = "QuantConnect.Lean.Engine.Results.LeanBridgeResultHandler"
    # Prevent Lean console launcher from blocking on "Press any key to continue." after exit.
    payload["close-automatically"] = True

    # Brokerage connection
    payload["ib-host"] = settings_row.host
    payload["ib-port"] = int(settings_row.port)
    payload["ib-client-id"] = int(client_id)
    payload["ib-trading-mode"] = str(mode)

    # Bridge output (writes command_results + open_orders snapshots here)
    payload["lean-bridge-output-dir"] = str(output_dir)
    # Keep cancel worker lightweight: no subscriptions unless explicitly configured.
    payload["lean-bridge-watchlist-path"] = ""
    payload["lean-bridge-watchlist-refresh-seconds"] = "0"
    payload["lean-bridge-heartbeat-seconds"] = "2"
    payload["lean-bridge-snapshot-seconds"] = "2"
    payload["lean-bridge-open-orders-seconds"] = "2"

    # Cancel command processing
    payload["lean-bridge-commands-enabled"] = True
    payload["lean-bridge-commands-seconds"] = "1"
    payload["lean-bridge-commands-dir"] = str(commands_dir)
    return payload


def _spawn_cancel_worker(
    *,
    order_id: int,
    mode: str,
    client_id: int,
    output_dir: Path,
    commands_dir: Path,
    command_id: str,
) -> None:
    # Best-effort. Never block API threads for too long.
    lock = JobLock(f"trade_cancel_worker_{int(order_id)}", data_root=resolve_bridge_root())
    if not lock.acquire():
        return
    try:
        from app.db import SessionLocal

        with SessionLocal() as session:
            config = _build_cancel_worker_config(
                session,
                mode=mode,
                client_id=client_id,
                output_dir=output_dir,
                commands_dir=commands_dir,
            )
        artifact_root = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")
        config_dir = artifact_root / "lean_execution"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"cancel_order_{int(order_id)}_{command_id}.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        pid = launch_execution_async(config_path=str(config_path))
        if pid <= 0:
            return

        result_path = output_dir / "command_results" / f"{command_id}.json"
        deadline = time.time() + _CANCEL_WORKER_TIMEOUT_SECONDS
        while time.time() < deadline:
            if result_path.exists():
                break
            time.sleep(0.5)

        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError, PermissionError):
            pass
    finally:
        lock.release()


def request_cancel_trade_order(
    session,
    *,
    order: TradeOrder,
    actor: str = "system",
) -> TradeOrder:
    """Request cancellation for a trade order.

    - Always allowed for NEW/SUBMITTED/PARTIAL (and idempotent for CANCEL_REQUESTED).
    - For terminal statuses, it's a no-op.
    - The broker cancel is performed asynchronously by a Lean bridge instance sharing the
      original IB client-id (execution process if still running; otherwise a short-lived
      cancel worker started by the backend).
    """
    if order is None:
        raise ValueError("order_not_found")

    status = str(order.status or "").strip().upper()
    if status in _TERMINAL_ORDER_STATUSES:
        return order

    tag = _resolve_order_tag(order)
    if not tag:
        raise ValueError("order_tag_missing")

    bridge_root = resolve_bridge_root()
    open_orders_payload = read_open_orders(bridge_root)
    # If the order is NEW but already visible in open orders, treat it as submitted and cancel anyway.
    # If the snapshot is empty/stale, we still enqueue the cancel command because it is safe/idempotent.
    tag_present = _open_orders_has_tag(open_orders_payload, tag)

    output_dir = _resolve_order_output_dir(session, order=order)
    commands_dir = output_dir / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    cmd = write_cancel_order_command(
        commands_dir,
        order_id=order.id,
        tag=tag,
        actor=actor,
        reason="user_cancel",
    )

    meta = {
        "command_id": cmd.command_id,
        "command_path": cmd.command_path,
        "requested_at": cmd.requested_at,
        "expires_at": cmd.expires_at,
        "tag": tag,
        "tag_present_in_open_orders": bool(tag_present),
        "output_dir": str(output_dir),
    }
    update_trade_order_status(
        session,
        order,
        {
            "status": "CANCEL_REQUESTED",
            "params": {
                "user_cancel": meta,
                "user_cancel_requested": True,
                "user_cancel_requested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        },
    )

    record_audit(
        session,
        action="trade_order.cancel_requested",
        resource_type="trade_order",
        resource_id=order.id,
        actor=actor,
        detail={
            "order_id": order.id,
            "tag": tag,
            "command_id": cmd.command_id,
            "command_path": cmd.command_path,
        },
    )
    session.commit()
    session.refresh(order)

    # Unit tests run on sqlite in-memory; never spawn external processes there.
    dialect = ""
    if getattr(session, "bind", None) is not None:
        dialect = str(getattr(session.bind, "dialect", None).name or "")

    if dialect.lower() != "sqlite":
        try:
            # Leader-submitted orders are canceled by the long-lived bridge command loop.
            if not _is_leader_submit_order(order):
                pid = _resolve_execution_pid(session, order=order)
                if not _pid_alive(pid):
                    client_id = _resolve_execution_client_id(session, order=order)
                    if client_id is not None:
                        mode = _resolve_execution_mode(session, order=order)
                        worker = threading.Thread(
                            target=_spawn_cancel_worker,
                            kwargs={
                                "order_id": int(order.id),
                                "mode": mode,
                                "client_id": int(client_id),
                                "output_dir": Path(output_dir),
                                "commands_dir": Path(commands_dir),
                                "command_id": cmd.command_id,
                            },
                            daemon=True,
                        )
                        worker.start()
        except Exception as exc:
            _LOG.warning("cancel worker spawn failed: order_id=%s err=%s", order.id, exc)
    return order
