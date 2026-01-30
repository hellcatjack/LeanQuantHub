from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.routes import brokerage as brokerage_routes
from app.routes import ib as ib_routes


def test_stream_status_maps_ok_to_connected(monkeypatch):
    def _fake_status(_root):
        return {"status": "ok", "last_heartbeat": "2026-01-30T00:00:00Z", "stale": False}

    def _fake_quotes(_root):
        return {"items": []}

    monkeypatch.setattr(brokerage_routes, "read_bridge_status", _fake_status)
    monkeypatch.setattr(brokerage_routes, "read_quotes", _fake_quotes)
    monkeypatch.setattr(brokerage_routes, "_resolve_bridge_root", lambda: Path("/tmp"))

    payload = brokerage_routes.get_ib_stream_status()
    assert payload.status == "connected"


def test_stream_status_maps_ok_to_connected_in_ib_route(monkeypatch):
    def _fake_status(_root):
        return {"status": "ok", "last_heartbeat": "2026-01-30T00:00:00Z", "stale": False}

    def _fake_quotes(_root):
        return {"items": []}

    monkeypatch.setattr(ib_routes, "read_bridge_status", _fake_status)
    monkeypatch.setattr(ib_routes, "read_quotes", _fake_quotes)
    monkeypatch.setattr(ib_routes, "_resolve_bridge_root", lambda: Path("/tmp"))

    payload = ib_routes.get_ib_stream_status()
    assert payload.status == "connected"


def test_stream_status_degraded_when_stale(monkeypatch):
    def _fake_status(_root):
        return {"status": "ok", "last_heartbeat": "2026-01-30T00:00:00Z", "stale": True}

    def _fake_quotes(_root):
        return {"items": []}

    monkeypatch.setattr(brokerage_routes, "read_bridge_status", _fake_status)
    monkeypatch.setattr(brokerage_routes, "read_quotes", _fake_quotes)
    monkeypatch.setattr(brokerage_routes, "_resolve_bridge_root", lambda: Path("/tmp"))

    payload = brokerage_routes.get_ib_stream_status()
    assert payload.status == "degraded"
