from pathlib import Path
import sys
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, PreTradeRun, PreTradeStep, Project, DecisionSnapshot
from app.services import pretrade_runner


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_pretrade_market_snapshot_calls_fetch(monkeypatch, tmp_path):
    session = _make_session()
    try:
        project = Project(name="pretrade-snap", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "items.csv"
        items_path.write_text("symbol\nSPY\nAAPL\n", encoding="utf-8")
        snapshot = DecisionSnapshot(project_id=project.id, items_path=str(items_path))
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        run = PreTradeRun(project_id=project.id, status="running", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        step = PreTradeStep(
            run_id=run.id,
            step_key="market_snapshot",
            step_order=9,
            status="queued",
            artifacts={"decision_snapshot_id": snapshot.id},
        )
        session.add(step)
        session.commit()
        session.refresh(step)

        called = {"ok": False, "symbols": None, "market_data_type": None}

        def _fetch_market_snapshots(_session, *, symbols, store, market_data_type=None, **_kwargs):
            called["ok"] = True
            called["symbols"] = symbols
            called["market_data_type"] = market_data_type
            return [{"symbol": "SPY", "data": {"last": 1.0}, "error": None}]

        monkeypatch.setattr(pretrade_runner, "fetch_market_snapshots", _fetch_market_snapshots)
        monkeypatch.setattr(
            pretrade_runner,
            "_resolve_project_config",
            lambda _session, _pid: {"trade": {"market_data_type": "delayed", "market_snapshot_ttl_seconds": 30}},
        )
        monkeypatch.setattr(pretrade_runner.ib_stream, "is_snapshot_fresh", lambda *_args, **_kwargs: False)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        result = pretrade_runner.step_market_snapshot(ctx, {})

        assert called["ok"] is True
        assert called["market_data_type"] == "delayed"
        assert "market_snapshot" in (result.artifacts or {})
    finally:
        session.close()


def test_pretrade_market_snapshot_filters_excluded_symbols(monkeypatch, tmp_path):
    session = _make_session()
    try:
        project = Project(name="pretrade-filter", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "items.csv"
        items_path.write_text("symbol\nSPY\nBRK.B\n1143.HK\nAAPL\n", encoding="utf-8")
        snapshot = DecisionSnapshot(project_id=project.id, items_path=str(items_path))
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        run = PreTradeRun(project_id=project.id, status="running", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        step = PreTradeStep(
            run_id=run.id,
            step_key="market_snapshot",
            step_order=9,
            status="queued",
            artifacts={"decision_snapshot_id": snapshot.id},
        )
        session.add(step)
        session.commit()
        session.refresh(step)

        called = {"symbols": None}

        def _fetch_market_snapshots(_session, *, symbols, store, market_data_type=None, **_kwargs):
            called["symbols"] = symbols
            return [{"symbol": "SPY", "data": {"last": 1.0}, "error": None}]

        monkeypatch.setattr(pretrade_runner, "fetch_market_snapshots", _fetch_market_snapshots)
        monkeypatch.setattr(
            pretrade_runner,
            "_resolve_project_config",
            lambda _session, _pid: {
                "trade": {
                    "market_data_type": "realtime",
                    "market_snapshot_ttl_seconds": 30,
                    "market_snapshot_exclude_symbols": ["BRK.B", "1143.HK"],
                }
            },
        )
        monkeypatch.setattr(pretrade_runner.ib_stream, "is_snapshot_fresh", lambda *_args, **_kwargs: False)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        pretrade_runner.step_market_snapshot(ctx, {})

        assert set(called["symbols"] or []) == {"SPY", "AAPL"}
    finally:
        session.close()


def test_pretrade_market_snapshot_uses_latest_snapshot_when_missing_artifacts(monkeypatch, tmp_path):
    session = _make_session()
    try:
        project = Project(name="pretrade-latest", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path_old = tmp_path / "items_old.csv"
        items_path_old.write_text("symbol\nSPY\n", encoding="utf-8")
        snapshot_old = DecisionSnapshot(
            project_id=project.id,
            items_path=str(items_path_old),
            created_at=pretrade_runner.datetime(2026, 1, 1, 11, 0, 0),
        )
        session.add(snapshot_old)
        session.commit()
        session.refresh(snapshot_old)

        items_path_new = tmp_path / "items_new.csv"
        items_path_new.write_text("symbol\nAAPL\n", encoding="utf-8")
        snapshot_new = DecisionSnapshot(
            project_id=project.id,
            items_path=str(items_path_new),
            created_at=pretrade_runner.datetime(2026, 1, 1, 13, 0, 0),
        )
        session.add(snapshot_new)
        session.commit()
        session.refresh(snapshot_new)

        run = PreTradeRun(
            project_id=project.id,
            status="running",
            params={},
            started_at=pretrade_runner.datetime(2026, 1, 1, 12, 0, 0),
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        step = PreTradeStep(
            run_id=run.id,
            step_key="market_snapshot",
            step_order=9,
            status="queued",
            artifacts=None,
        )
        session.add(step)
        session.commit()
        session.refresh(step)

        def _build_stream_symbols(_session, *, project_id, decision_snapshot_id=None, **_kwargs):
            assert decision_snapshot_id == snapshot_new.id
            return ["SPY"]

        def _fetch_market_snapshots(_session, *, symbols, store, market_data_type=None, **_kwargs):
            return [{"symbol": "SPY", "data": {"last": 1.0}, "error": None}]

        monkeypatch.setattr(pretrade_runner.ib_stream, "build_stream_symbols", _build_stream_symbols)
        monkeypatch.setattr(pretrade_runner, "fetch_market_snapshots", _fetch_market_snapshots)
        monkeypatch.setattr(
            pretrade_runner,
            "_resolve_project_config",
            lambda _session, _pid: {"trade": {"market_data_type": "delayed"}},
        )
        monkeypatch.setattr(pretrade_runner.ib_stream, "is_snapshot_fresh", lambda *_args, **_kwargs: False)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        pretrade_runner.step_market_snapshot(ctx, {})
    finally:
        session.close()
