from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, PreTradeRun, PreTradeStep, Project, TradeRun
import app.services.pretrade_runner as pretrade_runner


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_pretrade_can_trigger_trade_run(monkeypatch):
    Session = _make_session_factory()
    session = Session()

    def _fake_generate_decision_snapshot(*_args, **_kwargs):
        return {
            "summary": {"snapshot_date": "2026-01-16"},
            "summary_path": "/tmp/decision_summary.json",
            "items_path": "/tmp/decision_items.csv",
            "filters_path": "/tmp/decision_filters.csv",
            "artifact_dir": "/tmp/decision_artifacts",
            "log_path": "/tmp/decision.log",
        }

    monkeypatch.setattr(pretrade_runner, "generate_decision_snapshot", _fake_generate_decision_snapshot)

    try:
        project = Project(name="pretrade-test", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = PreTradeRun(project_id=project.id, status="running")
        session.add(run)
        session.commit()
        session.refresh(run)

        step = PreTradeStep(run_id=run.id, step_key="decision_snapshot", step_order=0, status="running")
        session.add(step)
        session.commit()
        session.refresh(step)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        result = pretrade_runner.step_decision_snapshot(ctx, {})

        trade_run_id = result.artifacts.get("trade_run_id") if result.artifacts else None
        decision_snapshot_id = result.artifacts.get("decision_snapshot_id") if result.artifacts else None

        assert trade_run_id is not None
        assert decision_snapshot_id is not None

        trade_run = session.get(TradeRun, trade_run_id)
        assert trade_run is not None
        assert trade_run.decision_snapshot_id == decision_snapshot_id
    finally:
        session.close()
