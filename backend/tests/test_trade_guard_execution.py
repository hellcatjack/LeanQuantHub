import os
from datetime import datetime
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models import Base, Project, TradeGuardState, TradeRun
import app.services.trade_executor as trade_executor


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_execute_blocked_when_guard_halted(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    os.environ["IB_API_MODE"] = "mock"

    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    session = Session()
    try:
        project = Project(name="guard-test", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = TradeRun(
            project_id=project.id,
            mode="paper",
            status="queued",
            decision_snapshot_id=1,
            params={"portfolio_value": 10000},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        guard = TradeGuardState(
            project_id=project.id,
            trade_date=datetime.utcnow().date(),
            mode="paper",
            status="halted",
            halt_reason={"reason": "manual"},
        )
        session.add(guard)
        session.commit()

        result = trade_executor.execute_trade_run(run.id, dry_run=True)
        assert result.status == "blocked"
        assert result.message == "guard_halted"
    finally:
        session.close()
