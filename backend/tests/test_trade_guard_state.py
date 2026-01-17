from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from datetime import date

from app.models import Base, TradeGuardState


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_trade_guard_state_model_fields():
    session = _make_session()
    try:
        state = TradeGuardState(project_id=1, trade_date=date(2026, 1, 17), mode="paper")
        session.add(state)
        session.flush()
        assert state.status == "active"
    finally:
        session.close()
