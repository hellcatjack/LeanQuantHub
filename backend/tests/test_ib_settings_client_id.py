from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, IBSettings
from app.services import ib_settings


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_ensure_ib_client_id_auto_increments(monkeypatch):
    session = _make_session()
    try:
        row = IBSettings(client_id=101, host="127.0.0.1", port=7497, api_mode="ib")
        session.add(row)
        session.commit()

        calls = {"n": 0}

        def _fake_probe(host, port, client_id, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                return ("disconnected", "ibapi error 326 clientId in use")
            return ("connected", "ibapi ok")

        monkeypatch.setattr(ib_settings, "_probe_ib_api", _fake_probe)

        updated = ib_settings.ensure_ib_client_id(session, max_attempts=3, timeout_seconds=0.1)
        assert updated.client_id == 102
    finally:
        session.close()


def test_probe_updates_client_id_on_conflict(monkeypatch):
    session = _make_session()
    try:
        row = IBSettings(client_id=101, host="127.0.0.1", port=7497, api_mode="ib")
        session.add(row)
        session.commit()

        calls = {"n": 0}

        def _fake_probe(host, port, client_id, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                return ("disconnected", "ibapi error 326 clientId in use")
            return ("connected", "ibapi ok")

        monkeypatch.setattr(ib_settings, "_probe_ib_api", _fake_probe)

        state = ib_settings.probe_ib_connection(session, timeout_seconds=0.1)
        assert state.status in {"connected", "mock"}
        session.refresh(row)
        assert row.client_id == 102
    finally:
        session.close()
