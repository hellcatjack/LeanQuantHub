from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_bridge_watchdog


def _iso_utc(*, seconds_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=max(0, seconds_ago))).isoformat()


def _set_file_age(path: Path, *, seconds_ago: int) -> None:
    aged = datetime.now(timezone.utc) - timedelta(seconds=max(0, seconds_ago))
    ts = aged.timestamp()
    os.utime(path, (ts, ts))


def test_ensure_lean_bridge_live_uses_leader(monkeypatch, tmp_path):
    called = {"value": False}

    def _ensure(session, *, mode: str, force: bool = False):
        called["value"] = True
        return {"status": "ok", "last_heartbeat": datetime.now(timezone.utc).isoformat()}

    monkeypatch.setattr(lean_bridge_watchdog, "ensure_lean_bridge_leader", _ensure)
    monkeypatch.setattr(lean_bridge_watchdog, "resolve_bridge_root", lambda: tmp_path)
    monkeypatch.setattr(
        lean_bridge_watchdog,
        "read_bridge_status",
        lambda _root: {"status": "ok", "stale": True, "last_heartbeat": None},
    )

    out = lean_bridge_watchdog.ensure_lean_bridge_live(None, mode="paper", force=False)

    assert called["value"] is True
    assert out.get("status") == "ok"


def test_refresh_bridge_force_does_not_force_restart_when_fresh(monkeypatch, tmp_path):
    calls: list[bool] = []
    (tmp_path / "account_summary.json").write_text(
        json.dumps(
            {
                "items": {"NetLiquidation": 30000},
                "refreshed_at": _iso_utc(seconds_ago=2),
                "stale": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "positions.json").write_text(
        json.dumps(
            {
                "items": [{"symbol": "AAPL", "quantity": 1}],
                "refreshed_at": _iso_utc(seconds_ago=2),
                "stale": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "quotes.json").write_text(
        json.dumps(
            {
                "items": [{"symbol": "AAPL", "last": 220.0, "timestamp": _iso_utc(seconds_ago=2)}],
                "updated_at": _iso_utc(seconds_ago=2),
                "stale": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "open_orders.json").write_text(
        json.dumps({"items": [], "refreshed_at": _iso_utc(seconds_ago=2), "stale": False}),
        encoding="utf-8",
    )

    def _ensure(session, *, mode: str, force: bool = False):
        calls.append(bool(force))
        return {"status": "ok", "last_heartbeat": datetime.now(timezone.utc).isoformat()}

    monkeypatch.setattr(lean_bridge_watchdog, "ensure_lean_bridge_leader", _ensure)
    monkeypatch.setattr(lean_bridge_watchdog, "resolve_bridge_root", lambda: tmp_path)
    monkeypatch.setattr(
        lean_bridge_watchdog,
        "read_bridge_status",
        lambda _root: {
            "status": "ok",
            "stale": False,
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        },
    )

    out = lean_bridge_watchdog.refresh_bridge(None, mode="paper", reason="force_check", force=True)

    assert calls == [False]
    assert out.get("last_refresh_result") == "success"


def test_refresh_bridge_force_triggers_restart_when_stale(monkeypatch, tmp_path):
    calls: list[bool] = []

    def _ensure(session, *, mode: str, force: bool = False):
        calls.append(bool(force))
        return {"status": "degraded", "stale": True, "last_heartbeat": None}

    monkeypatch.setattr(lean_bridge_watchdog, "ensure_lean_bridge_leader", _ensure)
    monkeypatch.setattr(lean_bridge_watchdog, "resolve_bridge_root", lambda: tmp_path)
    monkeypatch.setattr(
        lean_bridge_watchdog,
        "read_bridge_status",
        lambda _root: {"status": "degraded", "stale": True, "last_heartbeat": None},
    )

    lean_bridge_watchdog.refresh_bridge(None, mode="paper", reason="force_check", force=True)

    assert calls == [True]


def test_build_bridge_status_marks_stale_when_snapshots_are_old(monkeypatch, tmp_path):
    account_path = tmp_path / "account_summary.json"
    account_path.write_text(
        json.dumps(
            {
                "items": {"NetLiquidation": 30000},
                "refreshed_at": _iso_utc(seconds_ago=600),
                "stale": False,
            }
        ),
        encoding="utf-8",
    )
    positions_path = tmp_path / "positions.json"
    positions_path.write_text(
        json.dumps(
            {
                "items": [{"symbol": "AAPL", "quantity": 1}],
                "refreshed_at": _iso_utc(seconds_ago=600),
                "stale": False,
            }
        ),
        encoding="utf-8",
    )
    quotes_path = tmp_path / "quotes.json"
    quotes_path.write_text(
        json.dumps(
            {
                "items": [{"symbol": "AAPL", "last": 220.0, "timestamp": _iso_utc(seconds_ago=600)}],
                "updated_at": _iso_utc(seconds_ago=600),
                "stale": False,
            }
        ),
        encoding="utf-8",
    )
    open_orders_path = tmp_path / "open_orders.json"
    open_orders_path.write_text(
        json.dumps({"items": [], "refreshed_at": _iso_utc(seconds_ago=600), "stale": False}),
        encoding="utf-8",
    )
    _set_file_age(account_path, seconds_ago=600)
    _set_file_age(positions_path, seconds_ago=600)
    _set_file_age(quotes_path, seconds_ago=600)
    _set_file_age(open_orders_path, seconds_ago=600)
    monkeypatch.setattr(
        lean_bridge_watchdog,
        "read_bridge_status",
        lambda _root: {
            "status": "ok",
            "stale": False,
            "last_heartbeat": _iso_utc(seconds_ago=1),
        },
    )

    status = lean_bridge_watchdog.build_bridge_status(tmp_path)

    assert status.get("stale") is True
    reasons = status.get("stale_reasons") if isinstance(status.get("stale_reasons"), list) else []
    assert "account_summary_stale" in reasons
    assert "positions_stale" in reasons
    assert "quotes_stale" in reasons


def test_refresh_bridge_does_not_force_restart_when_only_snapshots_stale(monkeypatch, tmp_path):
    calls: list[bool] = []
    fresh_status = {
        "status": "ok",
        "stale": False,
        "last_heartbeat": _iso_utc(seconds_ago=1),
    }
    stale_account = {
        "items": {"NetLiquidation": 30000},
        "refreshed_at": _iso_utc(seconds_ago=600),
        "stale": False,
    }
    account_path = tmp_path / "account_summary.json"
    positions_path = tmp_path / "positions.json"
    quotes_path = tmp_path / "quotes.json"
    account_path.write_text(json.dumps(stale_account), encoding="utf-8")
    positions_path.write_text(
        json.dumps(
            {
                "items": [{"symbol": "AAPL", "quantity": 1}],
                "refreshed_at": _iso_utc(seconds_ago=600),
                "stale": False,
            }
        ),
        encoding="utf-8",
    )
    quotes_path.write_text(
        json.dumps(
            {
                "items": [{"symbol": "AAPL", "last": 220.0, "timestamp": _iso_utc(seconds_ago=600)}],
                "updated_at": _iso_utc(seconds_ago=600),
                "stale": False,
            }
        ),
        encoding="utf-8",
    )
    _set_file_age(account_path, seconds_ago=600)
    _set_file_age(positions_path, seconds_ago=600)
    _set_file_age(quotes_path, seconds_ago=600)

    def _ensure(session, *, mode: str, force: bool = False):
        calls.append(bool(force))
        return fresh_status

    monkeypatch.setattr(lean_bridge_watchdog, "ensure_lean_bridge_leader", _ensure)
    monkeypatch.setattr(lean_bridge_watchdog, "resolve_bridge_root", lambda: tmp_path)
    monkeypatch.setattr(lean_bridge_watchdog, "read_bridge_status", lambda _root: dict(fresh_status))

    out = lean_bridge_watchdog.refresh_bridge(None, mode="paper", reason="auto", force=False)

    assert calls == [False]
    assert out.get("last_refresh_result") == "failed"
