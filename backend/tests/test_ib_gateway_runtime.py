from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ib_gateway_runtime import (  # noqa: E402
    build_gateway_runtime_health,
    is_gateway_trade_blocked,
    load_gateway_runtime_health,
    write_gateway_runtime_health,
)
from app.services import ib_account as ib_account_module  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_runtime_health_marks_snapshot_stale_when_snapshots_stop_advancing(tmp_path):
    now = datetime(2026, 3, 10, 14, 5, 0, tzinfo=timezone.utc)
    stale_at = _iso(now - timedelta(minutes=5))

    payload = build_gateway_runtime_health(
        bridge_root=tmp_path,
        bridge_status={"status": "ok", "stale": False, "last_heartbeat": _iso(now - timedelta(seconds=2))},
        positions_payload={"stale": False, "refreshed_at": stale_at},
        open_orders_payload={"stale": False, "refreshed_at": stale_at},
        account_payload={"stale": False, "refreshed_at": stale_at},
        direct_probe={"ok": True, "latency_ms": 120},
        now=now,
    )

    assert payload["state"] == "snapshot_stale"
    assert payload["last_positions_at"] == stale_at
    assert payload["last_open_orders_at"] == stale_at
    assert payload["last_account_summary_at"] == stale_at
    assert payload["failure_count"] == 0


def test_runtime_health_marks_command_stuck_when_pending_command_too_old(tmp_path):
    now = datetime(2026, 3, 10, 14, 5, 0, tzinfo=timezone.utc)
    refreshed_at = _iso(now - timedelta(seconds=5))
    _write_json(
        tmp_path / "commands" / "cancel_order_1.json",
        {"requested_at": _iso(now - timedelta(minutes=4)), "symbol": "AAPL"},
    )
    _write_json(
        tmp_path / "command_results" / "cancel_order_1.json",
        {"completed_at": refreshed_at, "ok": True},
    )

    payload = build_gateway_runtime_health(
        bridge_root=tmp_path,
        bridge_status={"status": "ok", "stale": False, "last_heartbeat": _iso(now - timedelta(seconds=1))},
        positions_payload={"stale": False, "refreshed_at": refreshed_at},
        open_orders_payload={"stale": False, "refreshed_at": refreshed_at},
        account_payload={"stale": False, "refreshed_at": refreshed_at},
        direct_probe={"ok": True, "latency_ms": 90},
        now=now,
    )

    assert payload["state"] == "command_stuck"
    assert payload["pending_command_count"] == 1
    assert payload["oldest_pending_command_age_seconds"] >= 240
    assert payload["last_command_result_at"] == refreshed_at


def test_runtime_health_escalates_to_bridge_degraded_after_consecutive_probe_failures(tmp_path):
    now = datetime(2026, 3, 10, 14, 5, 0, tzinfo=timezone.utc)
    refreshed_at = _iso(now - timedelta(seconds=3))

    first = build_gateway_runtime_health(
        bridge_root=tmp_path,
        bridge_status={"status": "ok", "stale": False, "last_heartbeat": _iso(now - timedelta(seconds=1))},
        positions_payload={"stale": False, "refreshed_at": refreshed_at},
        open_orders_payload={"stale": False, "refreshed_at": refreshed_at},
        account_payload={"stale": False, "refreshed_at": refreshed_at},
        direct_probe={"ok": False, "latency_ms": 1500, "error": "timeout"},
        now=now,
    )
    second = build_gateway_runtime_health(
        bridge_root=tmp_path,
        bridge_status={"status": "ok", "stale": False, "last_heartbeat": _iso(now + timedelta(seconds=5))},
        positions_payload={"stale": False, "refreshed_at": _iso(now + timedelta(seconds=2))},
        open_orders_payload={"stale": False, "refreshed_at": _iso(now + timedelta(seconds=2))},
        account_payload={"stale": False, "refreshed_at": _iso(now + timedelta(seconds=2))},
        direct_probe={"ok": False, "latency_ms": 1500, "error": "timeout"},
        previous_payload=first,
        now=now + timedelta(seconds=5),
    )

    assert first["state"] == "healthy"
    assert first["failure_count"] == 1
    assert second["state"] == "bridge_degraded"
    assert second["failure_count"] == 2
    assert second["last_probe_result"] == "failure"
    assert second["last_probe_latency_ms"] == 1500
    assert is_gateway_trade_blocked(second) is True


def test_runtime_health_recovers_to_healthy_when_probe_succeeds(tmp_path):
    now = datetime(2026, 3, 10, 14, 5, 0, tzinfo=timezone.utc)
    previous = {
        "state": "bridge_degraded",
        "failure_count": 3,
        "last_recovery_action": "gateway_restart",
        "last_recovery_at": _iso(now - timedelta(minutes=1)),
        "next_allowed_action_at": _iso(now + timedelta(minutes=4)),
    }
    refreshed_at = _iso(now - timedelta(seconds=2))

    payload = build_gateway_runtime_health(
        bridge_root=tmp_path,
        bridge_status={"status": "ok", "stale": False, "last_heartbeat": _iso(now - timedelta(seconds=1))},
        positions_payload={"stale": False, "refreshed_at": refreshed_at},
        open_orders_payload={"stale": False, "refreshed_at": refreshed_at},
        account_payload={"stale": False, "refreshed_at": refreshed_at},
        direct_probe={"ok": True, "latency_ms": 85},
        previous_payload=previous,
        now=now,
    )

    assert payload["state"] == "healthy"
    assert payload["failure_count"] == 0
    assert payload["last_probe_result"] == "success"
    assert payload["last_probe_latency_ms"] == 85
    assert payload["last_recovery_action"] == "gateway_restart"
    assert payload["last_recovery_at"] == previous["last_recovery_at"]
    assert payload["next_allowed_action_at"] == previous["next_allowed_action_at"]
    assert is_gateway_trade_blocked(payload) is False


def test_runtime_health_round_trip_persists_payload(tmp_path):
    payload = {
        "state": "command_stuck",
        "failure_count": 1,
        "pending_command_count": 2,
        "oldest_pending_command_age_seconds": 180,
        "last_probe_result": "success",
    }

    written = write_gateway_runtime_health(tmp_path, payload)
    loaded = load_gateway_runtime_health(tmp_path)

    assert written["state"] == "command_stuck"
    assert written["pending_command_count"] == 2
    assert written["last_positions_at"] is None
    assert loaded["state"] == "command_stuck"
    assert loaded["pending_command_count"] == 2
    assert loaded["last_positions_at"] is None

    stored = json.loads((tmp_path / "gateway_runtime_health.json").read_text(encoding="utf-8"))
    assert "last_positions_at" in stored
    assert "last_recovery_action" in stored


def test_probe_positions_via_ibapi_uses_short_timeout_and_returns_success(monkeypatch):
    calls: list[tuple[object, str, str, float]] = []

    def _fake_fallback(session, *, mode: str, refreshed_at: object, timeout_seconds: float = 6.0):
        calls.append((session, mode, str(refreshed_at), timeout_seconds))
        return {
            "items": [{"symbol": "AAPL", "position": 2}],
            "refreshed_at": "2026-03-10T14:05:00Z",
            "source_detail": "ib_holdings_ibapi_fallback",
        }

    monotonic_values = iter((10.0, 10.045))
    monkeypatch.setattr(ib_account_module, "_load_positions_via_ibapi_fallback", _fake_fallback)
    monkeypatch.setattr(ib_account_module, "monotonic", lambda: next(monotonic_values))

    payload = ib_account_module.probe_positions_via_ibapi(object(), mode="paper")

    assert calls
    assert calls[0][1] == "paper"
    assert calls[0][3] == ib_account_module._IBAPI_VERIFY_SOFT_TIMEOUT_SECONDS
    assert payload == {
        "ok": True,
        "latency_ms": 45,
        "item_count": 1,
        "refreshed_at": "2026-03-10T14:05:00Z",
        "source_detail": "ib_holdings_ibapi_fallback",
    }


def test_probe_positions_via_ibapi_returns_failure_payload_when_fallback_fails(monkeypatch):
    calls: list[float] = []

    def _fake_fallback(_session, *, mode: str, refreshed_at: object, timeout_seconds: float = 6.0):
        assert mode == "live"
        assert isinstance(refreshed_at, str)
        calls.append(timeout_seconds)
        return None

    monotonic_values = iter((5.0, 5.02))
    monkeypatch.setattr(ib_account_module, "_load_positions_via_ibapi_fallback", _fake_fallback)
    monkeypatch.setattr(ib_account_module, "monotonic", lambda: next(monotonic_values))

    payload = ib_account_module.probe_positions_via_ibapi(object(), mode="live", timeout_seconds=0.1)

    assert calls == [0.3]
    assert payload["ok"] is False
    assert payload["latency_ms"] == 20
    assert payload["item_count"] == 0
    assert payload["error"] == "positions_probe_failed"
