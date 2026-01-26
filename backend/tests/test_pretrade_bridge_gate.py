from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, PreTradeRun, PreTradeStep, Project
from app.services import pretrade_runner


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def _write_payload(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_bridge_gate_fails_when_quotes_stale(tmp_path: Path, monkeypatch) -> None:
    session = _make_session()

    project = Project(name="gate", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    run = PreTradeRun(project_id=project.id, status="running")
    session.add(run)
    session.commit()
    session.refresh(run)

    step = PreTradeStep(run_id=run.id, step_key="bridge_gate", step_order=0, status="running")
    session.add(step)
    session.commit()
    session.refresh(step)

    now = datetime.now(timezone.utc)
    fresh = (now - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
    stale = (now - timedelta(seconds=120)).isoformat().replace("+00:00", "Z")

    _write_payload(tmp_path / "lean_bridge_status.json", {"last_heartbeat": fresh, "status": "ok"})
    _write_payload(tmp_path / "account_summary.json", {"updated_at": fresh, "items": []})
    _write_payload(tmp_path / "positions.json", {"updated_at": fresh, "items": []})
    _write_payload(tmp_path / "quotes.json", {"updated_at": stale, "items": [{"symbol": "SPY"}]})

    monkeypatch.setattr(pretrade_runner, "_resolve_bridge_root", lambda: tmp_path)

    ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
    with pytest.raises(RuntimeError):
        pretrade_runner.step_bridge_gate(ctx, {})

    session.refresh(step)
    gate = (step.artifacts or {}).get("bridge_gate")
    assert gate is not None
    assert "quotes" in gate.get("stale", [])
    session.close()
