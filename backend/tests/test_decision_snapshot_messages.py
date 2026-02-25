from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import db as app_db
from app.models import Base, DecisionSnapshot, Project
from app.routes import decisions as decision_routes
from app.schemas import DecisionSnapshotRequest
from app.services import decision_snapshot as decision_snapshot_service


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def test_build_snapshot_warning_message_includes_fallback_and_stale():
    summary = {
        "requested_snapshot_date": "2026-02-10",
        "effective_snapshot_date": "2026-02-06",
        "snapshot_age_days": 14,
        "snapshot_stale_days_threshold": 7,
        "warnings": [
            "requested_snapshot_unavailable_use_previous",
            "snapshot_stale:14d>7d",
        ],
    }

    message = decision_snapshot_service.build_snapshot_warning_message(summary)

    assert message is not None
    assert "2026-02-10" in message
    assert "2026-02-06" in message
    assert "14天" in message
    assert "7天" in message


def test_preview_decision_snapshot_returns_top_level_message(monkeypatch):
    @contextmanager
    def _get_session():
        yield object()

    def _resolve_backtest(*args, **kwargs):
        return 321, "explicit"

    def _preview_builder(*args, **kwargs):
        return {
            "params": {"project_id": 1},
            "summary": {
                "requested_snapshot_date": "2026-02-10",
                "effective_snapshot_date": "2026-02-06",
                "snapshot_age_days": 14,
                "snapshot_stale_days_threshold": 7,
                "warnings": [
                    "requested_snapshot_unavailable_use_previous",
                    "snapshot_stale:14d>7d",
                ],
            },
            "artifact_dir": "/tmp/artifact",
            "summary_path": "/tmp/summary.json",
            "items_path": "/tmp/items.csv",
            "filters_path": "/tmp/filters.csv",
            "items": [],
            "filters": [],
        }

    monkeypatch.setattr(decision_routes, "get_session", _get_session)
    monkeypatch.setattr(decision_routes, "resolve_backtest_run_link", _resolve_backtest)
    monkeypatch.setattr(decision_routes, "build_preview_decision_snapshot", _preview_builder)

    payload = DecisionSnapshotRequest(project_id=1, snapshot_date="2026-02-10")
    result = decision_routes.preview_decision_snapshot(payload)

    assert result.message is not None
    assert "2026-02-10" in result.message
    assert "2026-02-06" in result.message


def test_run_decision_snapshot_task_persists_warning_message(monkeypatch):
    Session = _make_session_factory()
    seed = Session()
    project = Project(name="project-warning-message", description="")
    seed.add(project)
    seed.commit()
    seed.refresh(project)
    snapshot = DecisionSnapshot(
        project_id=project.id,
        status="queued",
        params={"project_id": project.id, "snapshot_date": "2026-02-10"},
    )
    seed.add(snapshot)
    seed.commit()
    snapshot_id = snapshot.id
    seed.close()

    def _fake_generate(*args, **kwargs):
        return {
            "summary": {
                "snapshot_date": "2026-02-06",
                "requested_snapshot_date": "2026-02-10",
                "effective_snapshot_date": "2026-02-06",
                "snapshot_age_days": 14,
                "snapshot_stale_days_threshold": 7,
                "warnings": [
                    "requested_snapshot_unavailable_use_previous",
                    "snapshot_stale:14d>7d",
                ],
            },
            "params": {"project_id": project.id},
            "artifact_dir": "/tmp/artifact",
            "summary_path": "/tmp/summary.json",
            "items_path": "/tmp/items.csv",
            "filters_path": "/tmp/filters.csv",
            "log_path": "/tmp/log.txt",
        }

    monkeypatch.setattr(app_db, "SessionLocal", Session)
    monkeypatch.setattr(decision_snapshot_service, "generate_decision_snapshot", _fake_generate)

    decision_snapshot_service.run_decision_snapshot_task(snapshot_id)

    verify = Session()
    saved = verify.get(DecisionSnapshot, snapshot_id)
    assert saved is not None
    assert saved.status == "success"
    assert saved.message is not None
    assert "2026-02-10" in saved.message
    assert "2026-02-06" in saved.message
    verify.close()
