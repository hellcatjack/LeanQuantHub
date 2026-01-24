from pathlib import Path
import sys

from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.routes import ib as ib_routes


def test_get_account_summary_route(monkeypatch):
    def fake_summary(*args, **kwargs):
        return {
            "items": {"NetLiquidation": 100.0},
            "refreshed_at": None,
            "source": "cache",
            "stale": False,
            "full": False,
        }

    @contextmanager
    def _get_session():
        yield None

    monkeypatch.setattr(ib_routes, "get_session", _get_session)
    monkeypatch.setattr(ib_routes, "get_account_summary", fake_summary)
    app = FastAPI()
    app.include_router(ib_routes.router)
    client = TestClient(app)
    res = client.get("/api/ib/account/summary?mode=paper")
    assert res.status_code == 200
    assert res.json()["items"]["NetLiquidation"] == 100.0
