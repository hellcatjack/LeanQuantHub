from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project
from app.services import lean_bridge_leader
from app.services import ib_settings
from app.services import trade_guard


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


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_run_trade_guard_watchdog_scans_all_projects(monkeypatch):
    session = _make_session()
    try:
        session.add_all([Project(name="p1", description=""), Project(name="p2", description="")])
        session.commit()

        calls: list[tuple[int, str]] = []

        def _fake_eval(_session, *, project_id, mode, **_kwargs):
            calls.append((int(project_id), str(mode)))
            return {"status": "active"}

        monkeypatch.setattr(trade_guard, "evaluate_intraday_guard", _fake_eval)
        scanned = lean_bridge_leader._run_trade_guard_watchdog(session, modes=("paper", "live"))

        assert scanned == 4
        assert sorted(calls) == [
            (1, "live"),
            (1, "paper"),
            (2, "live"),
            (2, "paper"),
        ]
    finally:
        session.close()


def test_run_trade_guard_watchdog_reuses_ib_snapshot_per_mode(monkeypatch):
    session = _make_session()
    try:
        session.add_all([Project(name="p1", description=""), Project(name="p2", description="")])
        session.commit()

        snapshot_calls: list[str] = []
        eval_calls: list[tuple[int, str, object]] = []

        def _fake_snapshot(_session, *, mode):
            snapshot_calls.append(str(mode))
            return {"mode": str(mode), "stale": False}

        def _fake_eval(_session, *, project_id, mode, ib_snapshot=None, **_kwargs):
            eval_calls.append((int(project_id), str(mode), ib_snapshot))
            return {"status": "active"}

        monkeypatch.setattr(trade_guard, "load_guard_ib_snapshot", _fake_snapshot, raising=False)
        monkeypatch.setattr(trade_guard, "evaluate_intraday_guard", _fake_eval)

        scanned = lean_bridge_leader._run_trade_guard_watchdog(session, modes=("paper", "live"))

        assert scanned == 4
        assert snapshot_calls.count("paper") == 1
        assert snapshot_calls.count("live") == 1
        assert len(eval_calls) == 4
        for _project_id, mode, ib_snapshot in eval_calls:
            assert isinstance(ib_snapshot, dict)
            assert ib_snapshot.get("mode") == mode
    finally:
        session.close()
