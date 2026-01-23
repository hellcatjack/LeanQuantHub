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


def test_stream_start_writes_config(monkeypatch, tmp_path):
    @contextmanager
    def _get_session():
        yield None

    monkeypatch.setattr(ib_routes, "get_session", _get_session)
    monkeypatch.setattr(ib_routes.ib_stream, "_resolve_stream_root", lambda _: tmp_path)
    payload = ib_routes.IBStreamStartRequest(project_id=1, symbols=["SPY"], market_data_type="delayed")
    ib_routes.start_ib_stream(payload)
    config = ib_routes.ib_stream.read_stream_config(tmp_path)
    assert config["project_id"] == 1
    assert config["symbols"] == ["SPY"]


def test_stream_start_writes_refresh_params(monkeypatch, tmp_path):
    @contextmanager
    def _get_session():
        yield None

    monkeypatch.setattr(ib_routes, "get_session", _get_session)
    monkeypatch.setattr(ib_routes.ib_stream, "_resolve_stream_root", lambda _: tmp_path)
    payload = ib_routes.IBStreamStartRequest(
        project_id=1,
        symbols=["SPY"],
        market_data_type="delayed",
        refresh_interval_seconds=5,
        stale_seconds=15,
    )
    ib_routes.start_ib_stream(payload)
    config = ib_routes.ib_stream.read_stream_config(tmp_path)
    assert config["refresh_interval_seconds"] == 5
    assert config["stale_seconds"] == 15
