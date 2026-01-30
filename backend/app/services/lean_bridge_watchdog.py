from __future__ import annotations

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


def ensure_lean_bridge_live(session, *, mode: str, force: bool = False) -> dict[str, object]:
    root = resolve_bridge_root()
    status = read_bridge_status(root)
    if not force and not _is_stale(status, _DEFAULT_STALE_SECONDS):
        return status

    return ensure_lean_bridge_leader(session, mode=mode, force=force)
