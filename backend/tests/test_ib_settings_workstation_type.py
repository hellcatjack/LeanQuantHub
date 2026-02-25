from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base
from app.routes import brokerage as brokerage_routes
from app.schemas import IBSettingsUpdate
from app.services import ib_settings


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_resolve_default_settings_workstation_type_from_env(monkeypatch):
    monkeypatch.setenv("IB_WORKSTATION_TYPE", "Gateway")
    defaults = ib_settings._resolve_default_settings()
    assert defaults["workstation_type"] == "gateway"


def test_resolve_default_settings_workstation_type_invalid_fallback(monkeypatch):
    monkeypatch.setenv("IB_WORKSTATION_TYPE", "invalid")
    defaults = ib_settings._resolve_default_settings()
    assert defaults["workstation_type"] == "tws"


def test_update_brokerage_settings_accepts_gateway_workstation(monkeypatch):
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(brokerage_routes, "get_session", _get_session)

    payload = IBSettingsUpdate(workstation_type="gateway")
    out = brokerage_routes.update_ib_settings(payload)
    assert out.workstation_type == "gateway"
    session.close()


def test_update_brokerage_settings_normalizes_invalid_workstation(monkeypatch):
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(brokerage_routes, "get_session", _get_session)

    payload = IBSettingsUpdate(workstation_type="not_supported")
    out = brokerage_routes.update_ib_settings(payload)
    assert out.workstation_type == "tws"
    session.close()
