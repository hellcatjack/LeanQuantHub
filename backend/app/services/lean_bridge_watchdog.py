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


def _resolve_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_runner_script(mode: str) -> Path | None:
    root = _resolve_repo_root()
    if str(mode).lower() != "paper":
        candidate = root / "scripts" / "run_lean_live_interactive_paper.sh"
        return candidate if candidate.exists() else None
    candidate = root / "scripts" / "run_lean_live_interactive_paper.sh"
    return candidate if candidate.exists() else None


def _is_stale(status: dict, stale_seconds: int) -> bool:
    if status.get("stale") is True:
        return True
    heartbeat = parse_bridge_timestamp(status, ["last_heartbeat", "updated_at"])
    if heartbeat is None:
        return True
    now = datetime.now(timezone.utc)
    return now - heartbeat > timedelta(seconds=stale_seconds)


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
    stale_before_refresh = _is_stale(status, _DEFAULT_STALE_SECONDS)
    if not force and not stale_before_refresh:
        write_refresh_state(root, result="skipped", reason="fresh", message=None)
        return build_bridge_status(root)

    if not force and _should_rate_limit(root):
        write_refresh_state(root, result="skipped", reason="rate_limited", message=None)
        return build_bridge_status(root)

    # force refresh should not restart a healthy leader; only stale bridge requires force restart.
    ensure_lean_bridge_leader(session, mode=mode, force=bool(force and stale_before_refresh))
    status = read_bridge_status(root)
    if _is_stale(status, _DEFAULT_STALE_SECONDS):
        write_refresh_state(root, result="failed", reason=reason, message="stale_after_refresh")
    else:
        write_refresh_state(root, result="success", reason=reason, message=None)
    return build_bridge_status(root)


def ensure_lean_bridge_live(session, *, mode: str, force: bool = False) -> dict[str, object]:
    return refresh_bridge(session, mode=mode, reason="auto", force=force)
