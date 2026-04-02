#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging
import os
from queue import Empty, Queue
import subprocess
import sys
from threading import Thread
from time import monotonic

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.lstrip("\ufeff").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        parsed = value.strip().strip("'").strip('"')
        os.environ[key] = parsed


_load_env_file(BACKEND_ROOT / ".env")
_load_env_file(Path.home() / ".config" / "stocklean" / "ibgateway.env")

from app.core.config import settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.services.audit_log import record_audit  # noqa: E402
from app.services.ib_account import probe_positions_via_ibapi  # noqa: E402
from app.services.ib_gateway_runtime import (  # noqa: E402
    build_gateway_runtime_health,
    load_gateway_runtime_health,
    write_gateway_runtime_health,
)
from app.services.ib_settings import get_or_create_ib_settings  # noqa: E402
from app.services.lean_bridge_leader import ensure_lean_bridge_leader  # noqa: E402
from app.services.lean_bridge_paths import resolve_bridge_root  # noqa: E402
from app.services.lean_bridge_watchdog import refresh_bridge  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_SERVICE_NAME = "stocklean-ibgateway.service"
DEFAULT_MODE = "paper"
BRIDGE_REFRESH_THRESHOLD = 1
LEADER_RESTART_THRESHOLD = 2
GATEWAY_RESTART_THRESHOLD = 3
GATEWAY_RESTART_COOLDOWN_SECONDS = max(
    int(getattr(settings, "ib_gateway_restart_cooldown_seconds", 900) or 900),
    60,
)
PROBE_TIMEOUT_SECONDS = max(
    float(getattr(settings, "ib_gateway_runtime_probe_timeout_seconds", 0.35) or 0.35),
    0.3,
)
PROBE_HARD_TIMEOUT_SECONDS = max(
    float(getattr(settings, "ib_gateway_runtime_probe_hard_timeout_seconds", 1.5) or 1.5),
    0.5,
)
RECOVERY_QUIET_PERIOD_SECONDS = max(
    int(getattr(settings, "ib_gateway_recovery_quiet_period_seconds", 240) or 240),
    30,
)


def _utcnow(now: datetime | None = None) -> datetime:
    if isinstance(now, datetime):
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_mode(session, explicit_mode: str | None = None) -> str:
    mode_text = str(explicit_mode or "").strip().lower()
    if mode_text:
        return mode_text
    if session is None:
        return DEFAULT_MODE
    try:
        settings_row = get_or_create_ib_settings(session)
    except Exception:
        return DEFAULT_MODE
    mode_text = str(getattr(settings_row, "mode", "") or "").strip().lower()
    return mode_text or DEFAULT_MODE


def _cooldown_active(previous_payload: dict[str, object], *, now: datetime) -> bool:
    next_allowed = _parse_iso(previous_payload.get("next_allowed_action_at"))
    if next_allowed is None:
        return False
    return next_allowed > now


def _recovery_quiet_period_active(previous_payload: dict[str, object], *, now: datetime) -> bool:
    action = str(previous_payload.get("last_recovery_action") or "").strip().lower()
    if action not in {"leader_restart", "gateway_restart"}:
        return False
    recovered_at = _parse_iso(previous_payload.get("last_recovery_at"))
    if recovered_at is None:
        return False
    return (now - recovered_at).total_seconds() < RECOVERY_QUIET_PERIOD_SECONDS


def _record_recovery_audit(session, *, action: str, runtime_health: dict[str, object]) -> None:
    if session is None or not hasattr(session, "add"):
        return
    action_name = {
        "bridge_refresh": "brokerage.gateway.recovery_attempt",
        "leader_restart": "brokerage.gateway.leader_restart",
        "gateway_restart": "brokerage.gateway.restart",
        "gateway_degraded": "brokerage.gateway.degraded",
    }.get(action)
    if not action_name:
        return
    record_audit(
        session,
        action=action_name,
        resource_type="ib_gateway",
        detail={
            "state": runtime_health.get("state"),
            "failure_count": runtime_health.get("failure_count"),
            "recovery_failure_count": runtime_health.get("recovery_failure_count"),
            "last_probe_result": runtime_health.get("last_probe_result"),
        },
    )
    if hasattr(session, "commit"):
        try:
            session.commit()
        except Exception:
            logger.exception("Failed to commit gateway recovery audit")


def _systemd_restart_gateway(*, service_name: str, runner=subprocess.run) -> None:
    runner(
        ["systemctl", "--user", "restart", "--no-block", service_name],
        check=False,
    )


def _probe_positions_with_hard_timeout(
    session,
    *,
    mode: str,
    timeout_seconds: float,
    hard_timeout_seconds: float = PROBE_HARD_TIMEOUT_SECONDS,
    session_factory=None,
) -> dict[str, object]:
    normalized_timeout = max(0.3, float(timeout_seconds))
    effective_hard_timeout = max(0.05, float(hard_timeout_seconds))
    result_queue: Queue[tuple[str, dict[str, object] | None]] = Queue(maxsize=1)
    started_at = monotonic()

    def _resolve_session_context():
        if callable(session_factory):
            try:
                session_cm = session_factory()
            except Exception:
                logger.exception("Failed to open dedicated probe session; falling back to caller session")
            else:
                if session_cm is not None:
                    return session_cm
        return nullcontext(session)

    def _worker() -> None:
        try:
            with _resolve_session_context() as probe_session:
                payload = probe_positions_via_ibapi(
                    probe_session,
                    mode=mode,
                    timeout_seconds=normalized_timeout,
                )
        except Exception:
            logger.exception("Gateway direct probe failed inside watchdog worker")
            try:
                result_queue.put_nowait(("failure", None))
            except Exception:
                pass
            return
        try:
            result_queue.put_nowait(("success", payload if isinstance(payload, dict) else None))
        except Exception:
            pass

    worker = Thread(target=_worker, name="ib-gateway-watchdog-probe", daemon=True)
    worker.start()
    worker.join(timeout=effective_hard_timeout)
    if worker.is_alive():
        elapsed_ms = max(0, int(round((monotonic() - started_at) * 1000.0)))
        logger.error(
            "Gateway direct probe exceeded hard timeout mode=%s soft_timeout=%.3fs hard_timeout=%.3fs",
            mode,
            normalized_timeout,
            effective_hard_timeout,
        )
        return {
            "ok": False,
            "latency_ms": max(elapsed_ms, int(round(effective_hard_timeout * 1000.0))),
            "item_count": 0,
            "refreshed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "error": "probe_hard_timeout",
        }

    try:
        status, payload = result_queue.get_nowait()
    except Empty:
        status, payload = ("failure", None)
    if status == "success" and isinstance(payload, dict):
        return payload
    elapsed_ms = max(0, int(round((monotonic() - started_at) * 1000.0)))
    return {
        "ok": False,
        "latency_ms": elapsed_ms,
        "item_count": 0,
        "refreshed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "error": "positions_probe_failed",
    }


def run_gateway_watchdog_once(
    *,
    bridge_root: Path | str | None = None,
    session=None,
    mode: str | None = None,
    service_name: str = DEFAULT_SERVICE_NAME,
    now: datetime | None = None,
    direct_probe: dict[str, object] | None = None,
    probe_timeout_seconds: float = PROBE_TIMEOUT_SECONDS,
    restart_cooldown_seconds: int = GATEWAY_RESTART_COOLDOWN_SECONDS,
    subprocess_run=subprocess.run,
) -> dict[str, object]:
    root = Path(bridge_root) if bridge_root is not None else resolve_bridge_root()
    current_time = _utcnow(now)
    previous_payload = load_gateway_runtime_health(root)
    resolved_mode = _resolve_mode(session, explicit_mode=mode)

    if direct_probe is None and session is not None:
        try:
            direct_probe = _probe_positions_with_hard_timeout(
                session,
                mode=resolved_mode,
                timeout_seconds=probe_timeout_seconds,
                session_factory=get_session if callable(get_session) else None,
            )
        except Exception:
            logger.exception("Gateway direct probe failed; continuing without probe result")
            direct_probe = None

    runtime_health = build_gateway_runtime_health(
        bridge_root=root,
        previous_payload=previous_payload,
        direct_probe=direct_probe,
        now=current_time,
    )

    previous_state = str(previous_payload.get("state") or "").strip().lower()
    recovery_failure_count = int(previous_payload.get("recovery_failure_count") or 0)
    quiet_period_active = _recovery_quiet_period_active(previous_payload, now=current_time)
    action = "none"

    if runtime_health.get("state") == "healthy":
        runtime_health["recovery_failure_count"] = 0
        if previous_state == "gateway_restarting":
            runtime_health["state"] = "recovering"
        elif previous_state == "recovering":
            runtime_health["state"] = "healthy"
    elif quiet_period_active:
        runtime_health["recovery_failure_count"] = recovery_failure_count
        previous_action = str(previous_payload.get("last_recovery_action") or "").strip().lower()
        if previous_action == "gateway_restart":
            runtime_health["state"] = "gateway_restarting"
        elif previous_action == "leader_restart":
            runtime_health["state"] = "bridge_degraded"
    else:
        recovery_failure_count += 1
        runtime_health["recovery_failure_count"] = recovery_failure_count
        cooldown_active = _cooldown_active(previous_payload, now=current_time)
        if recovery_failure_count >= GATEWAY_RESTART_THRESHOLD:
            if cooldown_active:
                runtime_health["state"] = "gateway_degraded"
                action = "gateway_degraded"
            else:
                _systemd_restart_gateway(service_name=service_name, runner=subprocess_run)
                runtime_health["state"] = "gateway_restarting"
                action = "gateway_restart"
                runtime_health["next_allowed_action_at"] = _iso_z(
                    current_time + timedelta(seconds=max(60, int(restart_cooldown_seconds)))
                )
        elif recovery_failure_count >= LEADER_RESTART_THRESHOLD:
            try:
                ensure_lean_bridge_leader(session, mode=resolved_mode, force=True)
                action = "leader_restart"
            except Exception:
                logger.exception("Leader restart action failed")
        elif recovery_failure_count >= BRIDGE_REFRESH_THRESHOLD:
            try:
                refresh_bridge(session, mode=resolved_mode, reason="gateway_watchdog", force=True)
                action = "bridge_refresh"
            except Exception:
                logger.exception("Bridge refresh action failed")

    if action in {"bridge_refresh", "leader_restart", "gateway_restart"}:
        runtime_health["last_recovery_action"] = action
        runtime_health["last_recovery_at"] = _iso_z(current_time)
        _record_recovery_audit(session, action=action, runtime_health=runtime_health)
    elif action == "gateway_degraded":
        _record_recovery_audit(session, action=action, runtime_health=runtime_health)

    stored = write_gateway_runtime_health(root, runtime_health)
    stored["action"] = action
    stored["mode"] = resolved_mode
    return stored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one IB Gateway watchdog recovery check.")
    parser.add_argument("--mode", default=None)
    parser.add_argument("--service-name", default=DEFAULT_SERVICE_NAME)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session_cm = get_session() if callable(get_session) else nullcontext(None)
    with session_cm as session:
        payload = run_gateway_watchdog_once(
            session=session,
            mode=args.mode,
            service_name=args.service_name,
        )
    logger.info("ib_gateway_watchdog action=%s state=%s", payload.get("action"), payload.get("state"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
