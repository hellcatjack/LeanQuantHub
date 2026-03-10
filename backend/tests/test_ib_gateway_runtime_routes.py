from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import SessionLocal
from app.routes import brokerage as brokerage_routes
from app.services import ib_status_overview


def _runtime_health(state: str) -> dict[str, object]:
    return {
        "state": state,
        "failure_count": 2,
        "pending_command_count": 1,
        "oldest_pending_command_age_seconds": 240,
        "last_positions_at": "2026-03-10T14:00:00Z",
        "last_open_orders_at": "2026-03-10T14:00:00Z",
        "last_account_summary_at": "2026-03-10T14:00:00Z",
        "last_command_result_at": "2026-03-10T14:01:00Z",
        "last_probe_result": "failure",
        "last_probe_latency_ms": 1500,
        "last_recovery_action": "leader_restart",
        "last_recovery_at": "2026-03-10T14:02:00Z",
        "next_allowed_action_at": "2026-03-10T14:05:00Z",
    }


def test_get_bridge_status_exposes_runtime_health(monkeypatch):
    runtime_health = _runtime_health("command_stuck")

    monkeypatch.setattr(brokerage_routes, "_resolve_bridge_root", lambda: Path("/tmp/lean_bridge"))
    monkeypatch.setattr(
        brokerage_routes,
        "build_bridge_status",
        lambda _root: {"status": "ok", "stale": False, "stale_reasons": [], "last_heartbeat": "2026-03-10T14:00:02Z"},
    )
    monkeypatch.setattr(brokerage_routes, "load_gateway_runtime_health", lambda _root: {"failure_count": 1})
    monkeypatch.setattr(
        brokerage_routes,
        "build_gateway_runtime_health",
        lambda **_kwargs: dict(runtime_health),
    )

    payload = brokerage_routes.get_bridge_status()

    assert payload.status == "ok"
    assert payload.runtime_health is not None
    assert payload.runtime_health.state == "command_stuck"
    assert payload.runtime_health.failure_count == 2


def test_build_ib_status_overview_includes_gateway_runtime(monkeypatch):
    runtime_health = _runtime_health("bridge_degraded")

    monkeypatch.setattr(ib_status_overview, "refresh_leader_watchlist", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ib_status_overview, "_resolve_bridge_root", lambda: Path("/tmp/lean_bridge"))
    monkeypatch.setattr(ib_status_overview, "_read_connection", lambda _session: {"status": "ok"})
    monkeypatch.setattr(ib_status_overview, "_read_config", lambda _session: {"mode": "paper"})
    monkeypatch.setattr(ib_status_overview, "_read_stream_status", lambda: {"status": "connected"})
    monkeypatch.setattr(ib_status_overview, "_read_snapshot_cache", lambda: {"status": "fresh"})
    monkeypatch.setattr(ib_status_overview, "_read_orders", lambda _session: {"latest_order_id": None})
    monkeypatch.setattr(ib_status_overview, "_read_alerts", lambda _session: {"latest_alert_id": None})
    monkeypatch.setattr(ib_status_overview, "load_gateway_runtime_health", lambda _root: {"failure_count": 1})
    monkeypatch.setattr(
        ib_status_overview,
        "build_gateway_runtime_health",
        lambda **_kwargs: dict(runtime_health),
    )

    session = SessionLocal()
    try:
        payload = ib_status_overview.build_ib_status_overview(session)
    finally:
        session.close()

    assert payload["gateway_runtime"]["state"] == "bridge_degraded"
    assert payload["gateway_runtime"]["last_recovery_action"] == "leader_restart"


def test_get_ib_status_overview_route_exposes_gateway_runtime(monkeypatch):
    @contextmanager
    def _get_session():
        yield None

    monkeypatch.setattr(brokerage_routes, "get_session", _get_session)
    monkeypatch.setattr(
        brokerage_routes,
        "build_ib_status_overview",
        lambda _session: {
            "connection": {"status": "ok"},
            "config": {"mode": "paper"},
            "stream": {"status": "connected"},
            "snapshot_cache": {"status": "fresh"},
            "orders": {"latest_order_id": None},
            "alerts": {"latest_alert_id": None},
            "gateway_runtime": _runtime_health("snapshot_stale"),
            "partial": False,
            "errors": [],
            "refreshed_at": datetime.now(timezone.utc),
        },
    )

    payload = brokerage_routes.get_ib_status_overview()

    assert payload.gateway_runtime is not None
    assert payload.gateway_runtime.state == "snapshot_stale"
    assert payload.gateway_runtime.pending_command_count == 1
