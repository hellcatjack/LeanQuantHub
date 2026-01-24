from pathlib import Path
import sys

from contextlib import contextmanager

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.routes import brokerage as brokerage_routes


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

    monkeypatch.setattr(brokerage_routes, "get_session", _get_session)
    monkeypatch.setattr(brokerage_routes, "get_account_summary", fake_summary)
    resp = brokerage_routes.get_ib_account_summary(mode="paper", full=False)
    assert resp.items["NetLiquidation"] == 100.0
