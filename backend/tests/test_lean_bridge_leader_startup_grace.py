from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_bridge_leader


def test_should_restart_respects_startup_grace(monkeypatch):
    now = datetime.now(timezone.utc)
    state = {"pid": 123, "started_at": now.isoformat()}
    status = {"status": "missing"}

    monkeypatch.setattr(lean_bridge_leader, "_pid_alive", lambda _pid: True)

    should_restart = lean_bridge_leader._should_restart(
        status,
        state,
        timeout_seconds=60,
        now=now,
    )

    assert should_restart is False


def test_should_restart_after_grace(monkeypatch):
    now = datetime.now(timezone.utc)
    state = {"pid": 123, "started_at": (now - timedelta(seconds=120)).isoformat()}
    status = {"status": "missing"}

    monkeypatch.setattr(lean_bridge_leader, "_pid_alive", lambda _pid: True)

    should_restart = lean_bridge_leader._should_restart(
        status,
        state,
        timeout_seconds=60,
        now=now,
    )

    assert should_restart is True
