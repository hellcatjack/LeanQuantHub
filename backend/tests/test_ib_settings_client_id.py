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


def test_probe_ib_connection_uses_bridge_only(monkeypatch):
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
        monkeypatch.setattr(
            ib_settings,
            "_probe_ib_account_session",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("probe")),
            raising=False,
        )
        monkeypatch.setattr(
            ib_settings.socket,
            "create_connection",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("blocked")),
        )

        state = ib_settings.probe_ib_connection(session, timeout_seconds=0.1)
        assert state.status == "disconnected"
    finally:
        session.close()
