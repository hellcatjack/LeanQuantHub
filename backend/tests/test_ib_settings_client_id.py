from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from datetime import datetime, timedelta

from app.models import Base, IBConnectionState, IBSettings
from app.services import ib_settings


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_ensure_ib_client_id_no_probe(monkeypatch):
    session = _make_session()
    try:
        row = IBSettings(client_id=101, host="127.0.0.1", port=7497, api_mode="ib")
        session.add(row)
        session.commit()

        monkeypatch.setattr(
            ib_settings,
            "_probe_ib_api",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("probe")),
            raising=False,
        )

        updated = ib_settings.ensure_ib_client_id(session, max_attempts=3, timeout_seconds=0.1)
        assert updated.client_id == 101
    finally:
        session.close()


def test_default_client_id_is_101(monkeypatch):
    monkeypatch.delenv("IB_CLIENT_ID", raising=False)
    defaults = ib_settings._resolve_default_settings()
    assert defaults["client_id"] == 101


def test_probe_ib_connection_marks_disconnected_when_socket_unreachable(monkeypatch):
    session = _make_session()
    try:
        row = IBSettings(client_id=101, host="127.0.0.1", port=7497, api_mode="ib")
        session.add(row)
        session.commit()

        monkeypatch.setattr(
            ib_settings,
            "read_bridge_status",
            lambda *args, **kwargs: {"status": "ok", "stale": False, "last_error": None},
        )
        monkeypatch.setattr(
            ib_settings,
            "_probe_ib_socket",
            lambda *args, **kwargs: False,
            raising=False,
        )

        state = ib_settings.probe_ib_connection(session, timeout_seconds=0.1)
        assert state.status == "disconnected"
    finally:
        session.close()


def test_probe_ib_connection_connected_when_socket_ok(monkeypatch):
    session = _make_session()
    try:
        row = IBSettings(client_id=101, host="127.0.0.1", port=7497, api_mode="ib")
        session.add(row)
        session.commit()

        monkeypatch.setattr(
            ib_settings,
            "read_bridge_status",
            lambda *args, **kwargs: {"status": "ok", "stale": False, "last_error": None},
        )
        monkeypatch.setattr(
            ib_settings,
            "_probe_ib_socket",
            lambda *args, **kwargs: True,
            raising=False,
        )

        state = ib_settings.probe_ib_connection(session, timeout_seconds=0.1)
        assert state.status == "connected"
    finally:
        session.close()


def test_probe_ib_connection_keeps_connected_when_only_snapshots_stale(monkeypatch):
    session = _make_session()
    try:
        row = IBSettings(client_id=101, host="127.0.0.1", port=7497, api_mode="ib")
        session.add(row)
        session.commit()

        monkeypatch.setattr(
            ib_settings,
            "read_bridge_status",
            lambda *args, **kwargs: {
                "status": "ok",
                "stale": True,
                "stale_reasons": ["positions_stale", "quotes_stale"],
                "last_error": None,
            },
        )
        monkeypatch.setattr(
            ib_settings,
            "_probe_ib_socket",
            lambda *args, **kwargs: True,
            raising=False,
        )

        state = ib_settings.probe_ib_connection(session, timeout_seconds=0.1)
        assert state.status == "connected"
        assert "snapshot" in str(state.message or "").lower()
    finally:
        session.close()


def test_get_ib_state_cached_skips_probe_within_interval(monkeypatch):
    session = _make_session()
    try:
        settings_row = IBSettings(client_id=101, host="127.0.0.1", port=7497, api_mode="ib")
        state_row = IBConnectionState(
            status="connected",
            message="cached",
            last_heartbeat=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(settings_row)
        session.add(state_row)
        session.commit()

        monkeypatch.setattr(
            ib_settings,
            "probe_ib_connection",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not probe")),
        )

        state = ib_settings.get_ib_state_cached(
            session,
            probe_interval_seconds=60.0,
            timeout_seconds=0.1,
        )
        assert state.status == "connected"
        assert state.message == "cached"
    finally:
        session.close()


def test_get_ib_state_cached_probes_after_interval(monkeypatch):
    session = _make_session()
    try:
        settings_row = IBSettings(client_id=101, host="127.0.0.1", port=7497, api_mode="ib")
        state_row = IBConnectionState(
            status="connected",
            message="old",
            last_heartbeat=datetime.utcnow() - timedelta(seconds=120),
            updated_at=datetime.utcnow(),
        )
        session.add(settings_row)
        session.add(state_row)
        session.commit()

        called = {"probe": False}

        def _probe(*_args, **_kwargs):
            called["probe"] = True
            return state_row

        monkeypatch.setattr(ib_settings, "probe_ib_connection", _probe)
        ib_settings.get_ib_state_cached(
            session,
            probe_interval_seconds=30.0,
            timeout_seconds=0.1,
        )
        assert called["probe"] is True
    finally:
        session.close()
