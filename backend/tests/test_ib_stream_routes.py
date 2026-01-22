from contextlib import contextmanager
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.routes import ib as ib_routes


def test_stream_status_route(monkeypatch):
    @contextmanager
    def _get_session():
        yield None

    monkeypatch.setattr(ib_routes, "get_session", _get_session)
    monkeypatch.setattr(
        ib_routes.ib_stream,
        "get_stream_status",
        lambda *a, **k: {
            "status": "connected",
            "last_heartbeat": "2026-01-22T09:31:05Z",
            "subscribed_symbols": ["SPY"],
            "ib_error_count": 0,
            "last_error": None,
            "market_data_type": "delayed",
        },
    )
    resp = ib_routes.get_ib_stream_status()
    assert resp.status == "connected"
    assert resp.subscribed_symbols == ["SPY"]
