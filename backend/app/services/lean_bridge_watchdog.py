from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import settings
from app.services.job_lock import JobLock
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import parse_bridge_timestamp, read_bridge_status
from app.services.lean_bridge_leader import ensure_lean_bridge_leader

logger = logging.getLogger(__name__)

_REFRESH_LOCK_KEY = "lean_bridge_refresh"
_DEFAULT_REFRESH_SECONDS = 8
_DEFAULT_STALE_SECONDS = 30
_DEFAULT_REFRESH_INTERVAL_SECONDS = 10
_REFRESH_STATE_FILENAME = "lean_bridge_refresh.json"
_ACCOUNT_STALE_SECONDS = 300
_POSITIONS_STALE_SECONDS = 120
_QUOTES_STALE_SECONDS = 120
_OPEN_ORDERS_STALE_SECONDS = 300


def _resolve_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_runner_script(mode: str) -> Path | None:
    root = _resolve_repo_root()
    if str(mode).lower() != "paper":
        candidate = root / "scripts" / "run_lean_live_interactive_paper.sh"
        return candidate if candidate.exists() else None
    candidate = root / "scripts" / "run_lean_live_interactive_paper.sh"
    return candidate if candidate.exists() else None


def _heartbeat_stale(status: dict, stale_seconds: int) -> bool:
    if status.get("stale") is True:
        return True
    heartbeat = parse_bridge_timestamp(status, ["last_heartbeat", "updated_at"])
    if heartbeat is None:
        return True
    now = datetime.now(timezone.utc)
    return now - heartbeat > timedelta(seconds=stale_seconds)


def _file_mtime(path: Path) -> datetime | None:
    try:
        value = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None
    return value


def _effective_snapshot_timestamp(payload: dict | None, path: Path, *, keys: list[str]) -> datetime | None:
    payload_ts = parse_bridge_timestamp(payload, keys)
    file_ts = _file_mtime(path)
    if payload_ts is None:
        return file_ts
    if file_ts is None:
        return payload_ts
    # Some payload timestamps reflect market quote time instead of write time; keep the newer one.
    return file_ts if file_ts > payload_ts else payload_ts


def _is_payload_stale(
    payload: dict | None,
    *,
    path: Path,
    stale_seconds: int,
    timestamp_keys: list[str],
    stale_source_details: set[str] | None = None,
) -> bool:
    if not isinstance(payload, dict):
        return True
    if payload.get("stale") is True:
        return True
    source_detail = str(payload.get("source_detail") or "").strip().lower()
    if stale_source_details and source_detail in stale_source_details:
        return True
    ts = _effective_snapshot_timestamp(payload, path, keys=timestamp_keys)
    if ts is None:
        return True
    age = datetime.now(timezone.utc) - ts
    return age > timedelta(seconds=max(1, int(stale_seconds)))


def _snapshot_stale_reasons(root: Path) -> list[str]:
    reasons: list[str] = []
    account_path = root / "account_summary.json"
    account_payload = _read_json(account_path)
    if _is_payload_stale(
        account_payload,
        path=account_path,
        stale_seconds=_ACCOUNT_STALE_SECONDS,
        timestamp_keys=["refreshed_at", "updated_at"],
        stale_source_details={"ib_account_empty", "brokerage_unavailable", "ib_account_error"},
    ):
        reasons.append("account_summary_stale")

    positions_path = root / "positions.json"
    positions_payload = _read_json(positions_path)
    if _is_payload_stale(
        positions_payload,
        path=positions_path,
        stale_seconds=_POSITIONS_STALE_SECONDS,
        timestamp_keys=["refreshed_at", "updated_at"],
        stale_source_details={"brokerage_unavailable", "ib_holdings_error"},
    ):
        reasons.append("positions_stale")

    quotes_path = root / "quotes.json"
    quotes_payload = _read_json(quotes_path)
    if _is_payload_stale(
        quotes_payload,
        path=quotes_path,
        stale_seconds=_QUOTES_STALE_SECONDS,
        timestamp_keys=["refreshed_at", "updated_at"],
        stale_source_details={"brokerage_unavailable", "ib_quotes_error"},
    ):
        reasons.append("quotes_stale")

    open_orders_path = root / "open_orders.json"
    open_orders_payload = _read_json(open_orders_path)
    if _is_payload_stale(
        open_orders_payload,
        path=open_orders_path,
        stale_seconds=_OPEN_ORDERS_STALE_SECONDS,
        timestamp_keys=["refreshed_at", "updated_at"],
        stale_source_details={"brokerage_unavailable", "ib_open_orders_error"},
    ):
        reasons.append("open_orders_stale")

    return reasons


def _collect_stale_reasons(status: dict, *, stale_seconds: int, root: Path | None) -> list[str]:
    reasons: list[str] = []
    if _heartbeat_stale(status, stale_seconds):
        reasons.append("heartbeat_stale")
    if root is not None:
        reasons.extend(_snapshot_stale_reasons(root))
    return reasons


def _run_bridge_once(script: Path, timeout_seconds: int) -> None:
    try:
        subprocess.run([str(script)], check=False, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        logger.warning("Lean bridge refresh timed out after %ss", timeout_seconds)
    except Exception:
        logger.exception("Failed to run lean bridge refresh script")


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    text = ts.replace("Z", "+00:00")
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def read_refresh_state(root: Path) -> dict[str, object]:
    path = root / _REFRESH_STATE_FILENAME
    payload = _read_json(path) or {}
    return {
        "last_refresh_at": payload.get("last_refresh_at"),
        "last_refresh_result": payload.get("last_refresh_result", "unknown"),
        "last_refresh_reason": payload.get("last_refresh_reason", "unknown"),
        "last_refresh_message": payload.get("last_refresh_message"),
    }


def write_refresh_state(
    root: Path, *, result: str, reason: str, message: str | None
) -> dict[str, object]:
    payload = {
        "last_refresh_at": datetime.now(timezone.utc).isoformat(),
        "last_refresh_result": result,
        "last_refresh_reason": reason,
        "last_refresh_message": message,
    }
    path = root / _REFRESH_STATE_FILENAME
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return payload


def build_bridge_status(root: Path) -> dict[str, object]:
    status = dict(read_bridge_status(root))
    reasons = _collect_stale_reasons(status, stale_seconds=_DEFAULT_STALE_SECONDS, root=root)
    status["stale"] = bool(reasons)
    status["stale_reasons"] = reasons
    status.update(read_refresh_state(root))
    return status


def _should_rate_limit(root: Path) -> bool:
    refresh_state = read_refresh_state(root)
    last_refresh_at = _parse_iso(str(refresh_state.get("last_refresh_at") or ""))
    if last_refresh_at is None:
        return False
    now = datetime.now(timezone.utc)
    return now - last_refresh_at < timedelta(seconds=_DEFAULT_REFRESH_INTERVAL_SECONDS)


def refresh_bridge(session, *, mode: str, reason: str, force: bool = False) -> dict[str, object]:
    root = resolve_bridge_root()
    status = read_bridge_status(root)
    stale_reasons_before = _collect_stale_reasons(
        status,
        stale_seconds=_DEFAULT_STALE_SECONDS,
        root=root,
    )
    stale_before_refresh = bool(stale_reasons_before)
    if not force and not stale_before_refresh:
        write_refresh_state(root, result="skipped", reason="fresh", message=None)
        return build_bridge_status(root)

    if not force and _should_rate_limit(root):
        write_refresh_state(root, result="skipped", reason="rate_limited", message=None)
        return build_bridge_status(root)

    # Restart leader only when transport heartbeat is stale/missing.
    # Snapshot staleness alone should not trigger process restarts, otherwise
    # frequent status probes can create restart storms and client accumulation.
    stale_reason_set = {str(item).strip().lower() for item in stale_reasons_before}
    should_force_restart = "heartbeat_stale" in stale_reason_set
    ensure_lean_bridge_leader(session, mode=mode, force=should_force_restart)
    status = read_bridge_status(root)
    stale_reasons_after = _collect_stale_reasons(
        status,
        stale_seconds=_DEFAULT_STALE_SECONDS,
        root=root,
    )
    if stale_reasons_after:
        detail = ",".join(stale_reasons_after)
        write_refresh_state(root, result="failed", reason=reason, message=f"stale_after_refresh:{detail}")
    else:
        write_refresh_state(root, result="success", reason=reason, message=None)
    return build_bridge_status(root)


def ensure_lean_bridge_live(session, *, mode: str, force: bool = False) -> dict[str, object]:
    return refresh_bridge(session, mode=mode, reason="auto", force=force)
