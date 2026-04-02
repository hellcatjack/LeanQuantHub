from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import BacktestRun, Base, Project
from app.routes import decisions as decision_routes
from app.schemas import DecisionSnapshotRequest


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_decision_snapshot_run_invalid_backtest(monkeypatch):
    session = _make_session()
    project = Project(name="p-a", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(decision_routes, "get_session", _get_session)

    payload = DecisionSnapshotRequest(project_id=project.id, backtest_run_id=9999)
    try:
        decision_routes.run_decision_snapshot(payload, background_tasks=None)
    except Exception as exc:
        assert "backtest_run_not_found" in str(exc)


def test_decision_snapshot_run_defaults_to_current_project_without_explicit_backtest(monkeypatch):
    session = _make_session()
    project = Project(name="p-current", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    old_run = BacktestRun(project_id=project.id, status="success")
    session.add(old_run)
    session.commit()

    class _BackgroundTasks:
        def __init__(self):
            self.calls = []

        def add_task(self, fn, *args):
            self.calls.append((fn, args))

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(decision_routes, "get_session", _get_session)
    background_tasks = _BackgroundTasks()

    payload = DecisionSnapshotRequest(project_id=project.id)
    snapshot = decision_routes.run_decision_snapshot(payload, background_tasks=background_tasks)

    assert snapshot.backtest_run_id is None
    assert isinstance(snapshot.params, dict)
    assert snapshot.params.get("backtest_run_id") is None
    assert snapshot.params.get("backtest_link_status") == "current_project"
    assert len(background_tasks.calls) == 1
