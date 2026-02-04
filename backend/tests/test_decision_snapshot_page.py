from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, DecisionSnapshot, Project
from app.routes import decisions as decision_routes


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_decision_snapshot_page_filters(monkeypatch):
    session = _make_session()
    project_a = Project(name="p-a", description="")
    project_b = Project(name="p-b", description="")
    session.add_all([project_a, project_b])
    session.commit()
    session.refresh(project_a)
    session.refresh(project_b)

    session.add_all(
        [
            DecisionSnapshot(project_id=project_a.id, status="success", backtest_run_id=11),
            DecisionSnapshot(project_id=project_a.id, status="failed", backtest_run_id=12),
            DecisionSnapshot(project_id=project_b.id, status="success", backtest_run_id=11),
        ]
    )
    session.commit()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(decision_routes, "get_session", _get_session)

    resp = decision_routes.list_decision_snapshots_page(
        project_id=project_a.id,
        page=1,
        page_size=10,
        status="success",
        snapshot_date=None,
        backtest_run_id=11,
        keyword=None,
    )
    dumped = resp.model_dump()
    assert dumped["total"] == 1
    assert dumped["items"][0]["backtest_run_id"] == 11
    session.close()
