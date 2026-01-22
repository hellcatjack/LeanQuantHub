from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models import Base, IBHistoryJob
import app.services.ib_history_runner as ib_history_runner


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class _DummyLock:
    def __init__(self, *args, **kwargs):
        pass

    def acquire(self) -> bool:
        return True

    def release(self) -> None:
        return None


class _DummyAdapter:
    def __init__(self, calls: list[str]):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def request_historical_data(self, symbol, **kwargs):
        self.calls.append(symbol)
        bars = [
            {
                "date": "2024-01-02",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 100,
            }
        ]
        return bars, None


def test_ib_history_resume_skips_completed(monkeypatch, tmp_path):
    session_factory = _make_session_factory()
    session = session_factory()
    job = IBHistoryJob(
        status="queued",
        params={
            "symbols": ["AAPL", "MSFT"],
            "min_delay_seconds": 0.0,
            "resume": True,
        },
    )
    session.add(job)
    session.commit()
    job_id = job.id
    session.close()

    artifact_root = tmp_path / "artifacts"
    progress_dir = artifact_root / f"ib_history_job_{job_id}"
    progress_dir.mkdir(parents=True, exist_ok=True)
    (progress_dir / "progress.json").write_text(
        json.dumps({"completed": {"success": ["AAPL"], "failed": []}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    monkeypatch.setattr(settings, "artifact_root", str(artifact_root))
    monkeypatch.setattr(ib_history_runner, "SessionLocal", session_factory)
    monkeypatch.setattr(ib_history_runner, "JobLock", _DummyLock)
    monkeypatch.setattr(
        ib_history_runner,
        "get_or_create_ib_settings",
        lambda _session: SimpleNamespace(api_mode="mock"),
    )

    calls: list[str] = []

    @contextmanager
    def _noop_lock():
        yield

    monkeypatch.setattr(ib_history_runner, "ib_request_lock", lambda: _noop_lock())
    monkeypatch.setattr(
        ib_history_runner,
        "ib_adapter",
        lambda _settings, timeout=10.0: _DummyAdapter(calls),
    )

    ib_history_runner.run_ib_history_job(job_id)

    assert calls == ["MSFT"]
    payload = json.loads((progress_dir / "progress.json").read_text(encoding="utf-8"))
    completed = payload.get("completed") or {}
    assert "AAPL" in completed.get("success", [])
    assert "MSFT" in completed.get("success", [])
