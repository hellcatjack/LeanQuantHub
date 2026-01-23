from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base
from app.services.ib_settings import update_ib_state


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_ib_state_degraded_since_clears_on_recovery():
    session = _make_session()
    try:
        state = update_ib_state(session, status="degraded", message="ib down", heartbeat=True)
        assert state.degraded_since is not None
        state = update_ib_state(session, status="connected", message="ok", heartbeat=True)
        assert state.degraded_since is None
    finally:
        session.close()
