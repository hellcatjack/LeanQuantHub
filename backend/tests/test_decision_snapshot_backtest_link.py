from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, BacktestRun, MLPipelineRun, Project
from app.services.decision_snapshot import resolve_backtest_run_link


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_resolve_backtest_run_link_prefers_explicit():
    session = _make_session()
    project = Project(name="p1", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    run = BacktestRun(project_id=project.id, status="success")
    session.add(run)
    session.commit()
    session.refresh(run)

    resolved, status = resolve_backtest_run_link(
        session,
        project_id=project.id,
        pipeline_id=None,
        explicit_backtest_run_id=run.id,
    )
    assert resolved == run.id
    assert status == "explicit"
    session.close()


def test_resolve_backtest_run_link_pipeline_then_project():
    session = _make_session()
    project = Project(name="p1", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    pipeline = MLPipelineRun(project_id=project.id, name="pl", status="success")
    session.add(pipeline)
    session.commit()
    session.refresh(pipeline)

    pipeline_run = BacktestRun(
        project_id=project.id, pipeline_id=pipeline.id, status="success"
    )
    project_run = BacktestRun(project_id=project.id, status="success")
    session.add_all([pipeline_run, project_run])
    session.commit()

    resolved, status = resolve_backtest_run_link(
        session,
        project_id=project.id,
        pipeline_id=pipeline.id,
        explicit_backtest_run_id=None,
    )
    assert resolved == pipeline_run.id
    assert status == "auto_pipeline"

    resolved2, status2 = resolve_backtest_run_link(
        session,
        project_id=project.id,
        pipeline_id=None,
        explicit_backtest_run_id=None,
    )
    assert resolved2 == project_run.id
    assert status2 == "auto_project"
    session.close()


def test_resolve_backtest_run_link_missing():
    session = _make_session()
    project = Project(name="p1", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    resolved, status = resolve_backtest_run_link(
        session,
        project_id=project.id,
        pipeline_id=None,
        explicit_backtest_run_id=None,
    )
    assert resolved is None
    assert status == "missing"
    session.close()
