from pathlib import Path
import sys
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, PreTradeRun, PreTradeStep
from app.services import pretrade_runner


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_pretrade_calls_trade_execution(monkeypatch):
    session = _make_session()
    try:
        run = PreTradeRun(project_id=1, status="running", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        step = PreTradeStep(
            run_id=run.id,
            step_key="trade_execute",
            step_order=99,
            status="queued",
            artifacts={"trade_run_id": 123},
        )
        session.add(step)
        session.commit()
        session.refresh(step)

        called = {"ok": False, "run_id": None}

        def _execute_trade_run(run_id, *_, **__):
            called["ok"] = True
            called["run_id"] = run_id
            return SimpleNamespace(status="done", run_id=run_id)

        monkeypatch.setattr(pretrade_runner, "execute_trade_run", _execute_trade_run)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        pretrade_runner.step_trade_execute(ctx, {})

        assert called["ok"] is True
        assert called["run_id"] == 123
    finally:
        session.close()
