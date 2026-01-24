from pathlib import Path
import sys
from contextlib import contextmanager

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from types import SimpleNamespace
from app.services import ib_health
from app.routes import brokerage as brokerage_routes


def test_ib_health_combines_stream_and_probe(monkeypatch):
    monkeypatch.setattr(
        ib_health,
        "read_bridge_status",
        lambda _root: {"status": "connected", "last_heartbeat": "2026-01-24T00:00:00Z"},
    )
    monkeypatch.setattr(ib_health, "_resolve_bridge_root", lambda: Path("/tmp"))
    result = ib_health.build_ib_health(SimpleNamespace())
    assert result["connection_status"] == "connected"
    assert result["stream_status"] == "connected"


def test_ib_health_route(monkeypatch):
    @contextmanager
    def _get_session():
        yield None

    monkeypatch.setattr(brokerage_routes, "get_session", _get_session)
    monkeypatch.setattr(
        brokerage_routes,
        "build_ib_health",
        lambda _s: {"connection_status": "connected", "stream_status": "connected", "stream_last_heartbeat": None},
    )

    resp = brokerage_routes.get_ib_health()
    assert resp.connection_status == "connected"
    assert resp.stream_status == "connected"
