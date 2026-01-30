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


def test_write_watchlist_uses_refresh(monkeypatch, tmp_path):
    calls: dict = {}

    def _fake_refresh(session, max_symbols=200, bridge_root=None):
        calls["bridge_root"] = bridge_root
        return {"symbols": ["SPY"], "updated_at": "2026-01-01T00:00:00Z"}

    monkeypatch.setattr(lean_bridge_leader, "_bridge_root", lambda: tmp_path)
    monkeypatch.setattr(lean_bridge_leader, "refresh_leader_watchlist", _fake_refresh)

    path = lean_bridge_leader._write_watchlist(None)

    assert calls.get("bridge_root") == tmp_path
    assert path == tmp_path / "watchlist.json"
