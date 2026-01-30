from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.routes import brokerage as brokerage_routes


def test_get_ib_state_uses_probe(monkeypatch):
    @contextmanager
    def _get_session():
        yield None

    monkeypatch.setattr(brokerage_routes, "get_session", _get_session)

    dummy = SimpleNamespace(
        id=1,
        status="connected",
        message="ok",
        last_heartbeat=datetime.utcnow(),
        degraded_since=None,
        updated_at=datetime.utcnow(),
    )

    called = {"probe": False}

    def _probe(session):
        called["probe"] = True
        return dummy

    def _update(*_args, **_kwargs):
        raise AssertionError("update_ib_state should not be called")

    monkeypatch.setattr(brokerage_routes, "probe_ib_connection", _probe)
    monkeypatch.setattr(brokerage_routes, "update_ib_state", _update)

    out = brokerage_routes.get_ib_state()

    assert out.status == "connected"
    assert called["probe"] is True
