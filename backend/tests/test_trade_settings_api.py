from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base
from app.routes import trade as trade_routes
from app.schemas import TradeSettingsUpdate


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_trade_settings_defaults_roundtrip(monkeypatch):
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(trade_routes, "get_session", _get_session)

    resp = trade_routes.get_trade_settings()
    assert "risk_defaults" in resp.model_dump()

    updated = TradeSettingsUpdate(risk_defaults={"max_order_notional": 1000})
    resp2 = trade_routes.update_trade_settings(updated)
    assert resp2.risk_defaults["max_order_notional"] == 1000

    session.close()
