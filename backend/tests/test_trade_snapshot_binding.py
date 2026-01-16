from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, TradeRun
import app.services.trade_executor as trade_executor


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_trade_run_requires_decision_snapshot(monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)

    session = Session()
    try:
        project = Project(name="snapshot-test", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = TradeRun(project_id=project.id, mode="paper", status="queued", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        result = trade_executor.execute_trade_run(run.id, dry_run=True)
        assert result.status == "blocked"
        assert result.message and "decision_snapshot_required" in result.message
    finally:
        session.close()
