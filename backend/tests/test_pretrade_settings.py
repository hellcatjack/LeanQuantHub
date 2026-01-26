from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base
from app.routes import pretrade as pretrade_routes


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_pretrade_settings_bridge_gate_fields_present(monkeypatch):
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(pretrade_routes, "get_session", _get_session)

    resp = pretrade_routes.get_pretrade_settings()
    assert resp.bridge_heartbeat_ttl_seconds == 60
    assert resp.bridge_account_ttl_seconds == 300
    assert resp.bridge_positions_ttl_seconds == 300
    assert resp.bridge_quotes_ttl_seconds == 60

    session.close()
