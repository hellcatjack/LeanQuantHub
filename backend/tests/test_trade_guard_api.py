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
from app.schemas import TradeGuardEvaluateRequest


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_guard_state_api():
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    trade_routes.get_session = _get_session  # type: ignore[attr-defined]

    resp = trade_routes.get_trade_guard_state(project_id=1, mode="paper")
    assert resp.project_id == 1
    assert resp.status == "active"

    payload = TradeGuardEvaluateRequest(project_id=1, mode="paper", risk_params={"max_daily_loss": -0.2})
    resp2 = trade_routes.evaluate_trade_guard(payload)
    assert resp2.state.status == "active"
    assert resp2.result["status"] == resp2.state.status

    session.close()
