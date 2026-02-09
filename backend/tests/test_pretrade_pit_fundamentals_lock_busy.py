from __future__ import annotations

from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, PreTradeRun, PreTradeSettings, PreTradeStep, Project, PitFundamentalJob
from app.services import pretrade_runner


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_step_pit_fundamentals_does_not_create_job_when_lock_busy(monkeypatch):
    session = _make_session()
    try:
        session.add(Project(name="p1", description=None, is_archived=False))
        session.commit()

        run = PreTradeRun(project_id=1, status="running", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        # Ensure step_pit_fundamentals doesn't try to resolve project symbols in this unit test.
        session.add(PreTradeSettings(update_project_only=False))
        session.commit()

        step = PreTradeStep(run_id=run.id, step_key="pit_fundamentals", step_order=1, status="queued")
        session.add(step)
        session.commit()
        session.refresh(step)

        class BusyLock:
            def __init__(self, *args, **kwargs):
                pass

            def acquire(self):
                return False

            def release(self):
                return None

            def _read_metadata(self):
                return {"owner": "unit-test", "heartbeat_at": "0", "ttl_seconds": "900"}

        monkeypatch.setattr(pretrade_runner, "JobLock", BusyLock)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        with pytest.raises(RuntimeError) as exc:
            pretrade_runner.step_pit_fundamentals(ctx, {})

        assert str(exc.value) == "pit_fundamentals_blocked"
        assert session.query(PitFundamentalJob).count() == 0

        step_db = session.get(PreTradeStep, step.id)
        assert step_db is not None
        assert step_db.artifacts and step_db.artifacts.get("pit_fundamental_lock_busy") is True
    finally:
        session.close()

