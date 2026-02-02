from __future__ import annotations

from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import (
    Base,
    DecisionSnapshot,
    PreTradeRun,
    PreTradeSettings,
    PreTradeStep,
    Project,
)
from app.services import pretrade_runner


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_pretrade_run_fails_fast_on_market_snapshot_unavailable(monkeypatch, tmp_path):
    session = _make_session()
    session.close = lambda: None
    try:
        project = Project(name="pretrade-failfast", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "items.csv"
        items_path.write_text("symbol\nAAPL\nMSFT\n", encoding="utf-8")
        snapshot = DecisionSnapshot(project_id=project.id, items_path=str(items_path))
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        run = PreTradeRun(project_id=project.id, status="queued", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        settings = PreTradeSettings(max_retries=1, retry_base_delay_seconds=0, retry_max_delay_seconds=0)
        session.add(settings)
        session.commit()

        step = PreTradeStep(
            run_id=run.id,
            step_key="market_snapshot",
            step_order=1,
            status="queued",
            artifacts={"decision_snapshot_id": snapshot.id},
        )
        session.add(step)
        session.commit()
        session.refresh(step)

        class DummyLock:
            def __init__(self, *args, **kwargs):
                pass

            def acquire(self):
                return True

            def release(self):
                return None

        monkeypatch.setattr(pretrade_runner, "SessionLocal", lambda: session)
        monkeypatch.setattr(pretrade_runner, "JobLock", DummyLock)
        monkeypatch.setattr(pretrade_runner, "resolve_bridge_root", lambda: tmp_path)
        monkeypatch.setattr(pretrade_runner, "read_positions", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(pretrade_runner, "read_quotes", lambda *_args, **_kwargs: {"items": []})
        monkeypatch.setattr(
            pretrade_runner,
            "_resolve_project_config",
            lambda _session, _pid: {"trade": {"market_snapshot_ttl_seconds": 30}},
        )
        monkeypatch.setattr(pretrade_runner, "_notify_telegram", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(pretrade_runner.time, "sleep", lambda *_args, **_kwargs: None)

        pretrade_runner.run_pretrade_run(run.id)

        session.refresh(run)
        step_db = session.get(PreTradeStep, step.id)
        assert run.status == "failed"
        assert "行情快照" in (run.message or "")
        assert step_db is not None
        assert step_db.status == "failed"
        assert "行情快照" in (step_db.message or "")
    finally:
        session.close()
