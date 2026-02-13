from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeSettings
from app.schemas import TradeSettingsOut


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_trade_settings_includes_auto_recovery_defaults():
    session = _make_session()
    try:
        row = TradeSettings(risk_defaults={}, execution_data_source="ib", auto_recovery=None)
        session.add(row)
        session.commit()
        out = TradeSettingsOut.model_validate(row, from_attributes=True)
        assert out.auto_recovery is not None
        assert out.auto_recovery.get("new_timeout_seconds") == 45
        assert out.auto_recovery.get("unfilled_timeout_seconds") == 600
    finally:
        session.close()
