from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_bridge_leader
from app.services import ib_settings


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


def test_build_leader_config_uses_configured_poll_intervals(monkeypatch, tmp_path):
    fake_settings = SimpleNamespace(host="127.0.0.1", port=7497, client_id=7)

    monkeypatch.setattr(ib_settings, "get_or_create_ib_settings", lambda _session: fake_settings)
    monkeypatch.setattr(lean_bridge_leader, "_load_template_config", lambda _mode: {})
    monkeypatch.setattr(lean_bridge_leader.settings, "lean_bridge_watchlist_refresh_seconds", 9)
    monkeypatch.setattr(lean_bridge_leader.settings, "lean_bridge_snapshot_seconds", 3)
    monkeypatch.setattr(lean_bridge_leader.settings, "lean_bridge_open_orders_seconds", 4)
    monkeypatch.setattr(lean_bridge_leader.settings, "lean_bridge_executions_seconds", 5)
    monkeypatch.setattr(lean_bridge_leader.settings, "lean_bridge_commands_seconds", 2)

    payload, _client_id = lean_bridge_leader._build_leader_config(
        None,
        mode="paper",
        watchlist_path=tmp_path / "watchlist.json",
    )

    assert payload["lean-bridge-watchlist-refresh-seconds"] == "9"
    assert payload["lean-bridge-snapshot-seconds"] == "3"
    assert payload["lean-bridge-open-orders-seconds"] == "4"
    assert payload["lean-bridge-executions-seconds"] == "5"
    assert payload["lean-bridge-commands-seconds"] == "2"


def test_interval_due_respects_elapsed_time():
    assert lean_bridge_leader._interval_due(last_run_mono=0.0, now_mono=100.0, interval_seconds=15.0) is True
    assert lean_bridge_leader._interval_due(last_run_mono=100.0, now_mono=110.0, interval_seconds=15.0) is False
    assert lean_bridge_leader._interval_due(last_run_mono=100.0, now_mono=115.1, interval_seconds=15.0) is True
