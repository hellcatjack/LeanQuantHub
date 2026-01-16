import os
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models import Base, Project, TradeRun
from app.services.trade_orders import create_trade_order
import app.services.trade_executor as trade_executor


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_risk_gate_blocks_large_single_position(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    os.environ["IB_API_MODE"] = "mock"

    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    session = Session()
    try:
        project = Project(name="risk-test", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = TradeRun(
            project_id=project.id,
            mode="paper",
            status="queued",
            params={"risk": {"max_order_notional": 1000}},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        create_trade_order(
            session,
            {
                "client_order_id": "run-1-SPY",
                "symbol": "SPY",
                "side": "BUY",
                "quantity": 20,
                "order_type": "LMT",
                "limit_price": 100,
            },
            run_id=run.id,
        )
        session.commit()

        result = trade_executor.execute_trade_run(run.id, dry_run=True)
        assert result.status == "blocked"
    finally:
        session.close()
