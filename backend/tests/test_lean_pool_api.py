from pathlib import Path
import sys
from contextlib import contextmanager

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.routes import brokerage as brokerage_routes


def test_lean_pool_status_route_registered():
    paths = {route.path for route in brokerage_routes.router.routes}
    assert "/api/brokerage/lean/pool/status" in paths


def test_get_lean_pool_status(monkeypatch):
    @contextmanager
    def _get_session():
        yield None

    monkeypatch.setattr(brokerage_routes, "get_session", _get_session)
    monkeypatch.setattr(brokerage_routes, "_fetch_lean_pool_status", lambda *_args, **_kwargs: [{"client_id": 1}])
    resp = brokerage_routes.get_lean_pool_status(mode="paper")
    assert resp["mode"] == "paper"
    assert resp["count"] == 1
