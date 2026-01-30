from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import SessionLocal
from app.services import ib_status_overview


def test_ib_status_overview_shape():
    session = SessionLocal()
    try:
        data = ib_status_overview.build_ib_status_overview(session)
    finally:
        session.close()
    assert "connection" in data
    assert "config" in data
    assert "stream" in data
    assert "snapshot_cache" in data
    assert "orders" in data
    assert "alerts" in data
    assert "refreshed_at" in data


def test_ib_status_overview_partial(monkeypatch):
    def broken_stream():
        raise RuntimeError("boom")

    monkeypatch.setattr(ib_status_overview, "_read_stream_status", broken_stream)
    session = SessionLocal()
    try:
        data = ib_status_overview.build_ib_status_overview(session)
    finally:
        session.close()
    assert data["partial"] is True
    assert "stream" in data["errors"]


def test_ib_status_overview_stream_from_bridge(monkeypatch):
    def _fake_bridge(_root):
        return {
            "status": "connected",
            "last_heartbeat": "2026-01-24T00:00:00Z",
            "error_count": 2,
            "last_error": "ok",
            "market_data_type": "realtime",
        }

    monkeypatch.setattr(ib_status_overview, "read_bridge_status", _fake_bridge)
    monkeypatch.setattr(ib_status_overview, "_resolve_bridge_root", lambda: Path("/tmp"))
    session = SessionLocal()
    try:
        data = ib_status_overview.build_ib_status_overview(session)
    finally:
        session.close()
    assert data["stream"]["status"] == "connected"
    assert data["stream"]["ib_error_count"] == 2


def test_ib_status_overview_refreshes_watchlist(monkeypatch):
    called = {"value": False}

    def _refresh(_session, max_symbols=200):
        called["value"] = True
        return {"symbols": [], "updated_at": "2026-01-01T00:00:00Z"}

    monkeypatch.setattr(
        ib_status_overview,
        "refresh_leader_watchlist",
        _refresh,
        raising=False,
    )

    session = SessionLocal()
    try:
        ib_status_overview.build_ib_status_overview(session)
    finally:
        session.close()

    assert called["value"] is True
