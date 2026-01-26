from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, PreTradeRun, PreTradeStep, Project
from app.routes import pretrade as pretrade_routes


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_pretrade_cancel_queued_marks_canceled(monkeypatch):
    session = _make_session()

    project = Project(name="p", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    run = PreTradeRun(project_id=project.id, status="queued")
    session.add(run)
    session.commit()
    session.refresh(run)

    step = PreTradeStep(run_id=run.id, step_key="x", step_order=0, status="queued")
    session.add(step)
    session.commit()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(pretrade_routes, "get_session", _get_session)

    resp = pretrade_routes.cancel_pretrade_run(run.id)
    assert resp.status == "canceled"

    refreshed = session.get(PreTradeRun, run.id)
    assert refreshed.status == "canceled"
    steps = session.query(PreTradeStep).filter(PreTradeStep.run_id == run.id).all()
    assert all(step.status == "canceled" for step in steps)

    session.close()


def test_pretrade_cancel_requested_normalized_on_detail(monkeypatch):
    session = _make_session()

    project = Project(name="p2", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    run = PreTradeRun(project_id=project.id, status="cancel_requested")
    session.add(run)
    session.commit()
    session.refresh(run)

    step = PreTradeStep(run_id=run.id, step_key="x", step_order=0, status="success")
    session.add(step)
    session.commit()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(pretrade_routes, "get_session", _get_session)

    resp = pretrade_routes.get_pretrade_run(run.id)
    assert resp.run.status == "canceled"

    session.close()
