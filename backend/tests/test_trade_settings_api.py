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
    dumped = resp.model_dump()
    assert "risk_defaults" in dumped
    assert "execution_data_source" in dumped
    assert dumped["risk_defaults"]["max_daily_loss"] == -0.05
    assert dumped["risk_defaults"]["max_intraday_drawdown"] == 0.08
    assert dumped["risk_defaults"]["cooldown_seconds"] == 900
    assert dumped.get("deadband_min_notional") == 0.0
    assert dumped.get("deadband_min_weight") == 0.0

    updated = TradeSettingsUpdate(
        risk_defaults={
            "max_order_notional": 1000,
            "max_daily_loss": 0.2,
            "max_intraday_drawdown": -0.3,
            "cooldown_seconds": -10,
        },
        deadband_min_notional=1500.0,
        deadband_min_weight=0.01,
    )
    resp2 = trade_routes.update_trade_settings(updated)
    assert resp2.risk_defaults["max_order_notional"] == 1000
    assert resp2.risk_defaults["max_daily_loss"] == -0.2
    assert resp2.risk_defaults["max_intraday_drawdown"] == 0.3
    assert resp2.risk_defaults["cooldown_seconds"] == 0
    assert resp2.risk_defaults["deadband_min_notional"] == 1500.0
    assert resp2.risk_defaults["deadband_min_weight"] == 0.01
    assert resp2.deadband_min_notional == 1500.0
    assert resp2.deadband_min_weight == 0.01

    session.close()


def test_trade_settings_execution_data_source_allows_lean(monkeypatch):
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(trade_routes, "get_session", _get_session)

    updated = TradeSettingsUpdate(
        risk_defaults={"max_order_notional": 2000},
        execution_data_source="lean",
    )
    resp = trade_routes.update_trade_settings(updated)
    dumped = resp.model_dump()
    assert dumped.get("execution_data_source") == "lean"

    session.close()
