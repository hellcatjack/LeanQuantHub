from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, PreTradeRun, PreTradeStep
from app.routes import pretrade as pretrade_routes


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed_run(session, step_statuses):
    project = Project(name="demo")
    session.add(project)
    session.commit()
    run = PreTradeRun(project_id=project.id, status="cancel_requested")
    session.add(run)
    session.commit()
    for idx, status in enumerate(step_statuses):
        step = PreTradeStep(
            run_id=run.id,
            step_key=f"step_{idx}",
            step_order=idx,
            status=status,
        )
        session.add(step)
    session.commit()
    return run.id


def test_finalize_cancel_sets_queued_steps_canceled():
    Session = _make_session()
    session = Session()
    try:
        run_id = _seed_run(session, ["queued", "success"])
        run = session.get(PreTradeRun, run_id)
        changed = pretrade_routes._finalize_cancel_if_possible(session, run)
        session.refresh(run)
        steps = session.query(PreTradeStep).filter(PreTradeStep.run_id == run_id).all()
        statuses = {step.status for step in steps}
    finally:
        session.close()

    assert changed is True
    assert run.status == "canceled"
    assert "queued" not in statuses
    assert "canceled" in statuses


def test_finalize_cancel_skips_when_running_step(monkeypatch):
    monkeypatch.setattr(pretrade_routes, "_pretrade_lock_active", lambda: True)
    Session = _make_session()
    session = Session()
    try:
        run_id = _seed_run(session, ["running", "queued"])
        run = session.get(PreTradeRun, run_id)
        changed = pretrade_routes._finalize_cancel_if_possible(session, run)
        session.refresh(run)
        steps = session.query(PreTradeStep).filter(PreTradeStep.run_id == run_id).all()
        statuses = {step.status for step in steps}
    finally:
        session.close()

    assert changed is False
    assert run.status == "cancel_requested"
    assert "running" in statuses
    assert "queued" in statuses


def test_finalize_cancel_clears_running_when_lock_inactive(monkeypatch):
    monkeypatch.setattr(pretrade_routes, "_pretrade_lock_active", lambda: False)

    Session = _make_session()
    session = Session()
    try:
        run_id = _seed_run(session, ["running", "queued"])
        run = session.get(PreTradeRun, run_id)
        changed = pretrade_routes._finalize_cancel_if_possible(session, run)
        session.refresh(run)
        steps = session.query(PreTradeStep).filter(PreTradeStep.run_id == run_id).all()
        statuses = {step.status for step in steps}
    finally:
        session.close()

    assert changed is True
    assert run.status == "canceled"
    assert "running" not in statuses
    assert "canceled" in statuses


def test_finalize_cancel_keeps_running_when_lock_active(monkeypatch):
    monkeypatch.setattr(pretrade_routes, "_pretrade_lock_active", lambda: True)

    Session = _make_session()
    session = Session()
    try:
        run_id = _seed_run(session, ["running", "queued"])
        run = session.get(PreTradeRun, run_id)
        changed = pretrade_routes._finalize_cancel_if_possible(session, run)
        session.refresh(run)
        steps = session.query(PreTradeStep).filter(PreTradeStep.run_id == run_id).all()
        statuses = {step.status for step in steps}
    finally:
        session.close()

    assert changed is False
    assert run.status == "cancel_requested"
    assert "running" in statuses
