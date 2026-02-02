from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

import pytest
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


def _quotes_payload(symbols: list[str]) -> dict:
    now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    return {
        "items": [{"symbol": symbol, "last": 1.0, "timestamp": now} for symbol in symbols],
        "updated_at": now,
        "stale": False,
    }


def _quotes_payload_with_old_items(symbols: list[str], *, updated_at: datetime) -> dict:
    fresh = updated_at.replace(microsecond=0).isoformat() + "Z"
    old = (updated_at - timedelta(minutes=5)).replace(microsecond=0).isoformat() + "Z"
    return {
        "items": [{"symbol": symbol, "last": 1.0, "timestamp": old} for symbol in symbols],
        "updated_at": fresh,
        "stale": False,
    }


def test_pretrade_market_snapshot_min_ttl_allows_recent_updated_at(monkeypatch, tmp_path):
    session = _make_session()
    try:
        project = Project(name="pretrade-min-ttl", description="")
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

        now = datetime.utcnow()
        updated_at = now - timedelta(seconds=90)
        monkeypatch.setattr(
            pretrade_runner,
            "read_quotes",
            lambda *_args, **_kwargs: _quotes_payload_with_old_items(["SPY", "AAPL"], updated_at=updated_at),
        )
        monkeypatch.setattr(
            pretrade_runner,
            "_resolve_project_config",
            lambda _session, _pid: {"trade": {"market_snapshot_ttl_seconds": 30}},
        )
        monkeypatch.setattr(pretrade_runner, "resolve_bridge_root", lambda: tmp_path)
        monkeypatch.setattr(pretrade_runner, "_resolve_bridge_root", lambda: tmp_path)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        result = pretrade_runner.step_market_snapshot(ctx, {})

        assert result.artifacts is not None
        assert result.artifacts["market_snapshot"]["skipped"] is True
    finally:
        session.close()


def test_pretrade_market_snapshot_skips_when_quotes_ready(monkeypatch, tmp_path):
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

        monkeypatch.setattr(pretrade_runner, "read_quotes", lambda *_args, **_kwargs: _quotes_payload(["SPY", "AAPL"]))
        monkeypatch.setattr(
            pretrade_runner,
            "_resolve_project_config",
            lambda _session, _pid: {"trade": {"market_snapshot_ttl_seconds": 30}},
        )

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        result = pretrade_runner.step_market_snapshot(ctx, {})

        assert result.artifacts is not None
        assert result.artifacts["market_snapshot"]["skipped"] is True
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

        monkeypatch.setattr(pretrade_runner, "read_quotes", lambda *_args, **_kwargs: _quotes_payload(["SPY", "AAPL"]))
        monkeypatch.setattr(
            pretrade_runner,
            "_resolve_project_config",
            lambda _session, _pid: {
                "trade": {
                    "market_snapshot_ttl_seconds": 30,
                    "market_snapshot_exclude_symbols": ["BRK.B", "1143.HK"],
                }
            },
        )

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        result = pretrade_runner.step_market_snapshot(ctx, {})

        assert result.artifacts is not None
        assert result.artifacts["market_snapshot"]["excluded_symbols"] == ["1143.HK", "BRK.B"]
    finally:
        session.close()


def test_pretrade_market_snapshot_uses_updated_at_over_item_timestamp(monkeypatch, tmp_path):
    session = _make_session()
    try:
        project = Project(name="pretrade-updated", description="")
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

        now = datetime.utcnow()
        monkeypatch.setattr(
            pretrade_runner,
            "read_quotes",
            lambda *_args, **_kwargs: _quotes_payload_with_old_items(["SPY", "AAPL"], updated_at=now),
        )
        monkeypatch.setattr(
            pretrade_runner,
            "_resolve_project_config",
            lambda _session, _pid: {"trade": {"market_snapshot_ttl_seconds": 30}},
        )
        monkeypatch.setattr(pretrade_runner, "resolve_bridge_root", lambda: tmp_path)
        monkeypatch.setattr(pretrade_runner, "_resolve_bridge_root", lambda: tmp_path)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        result = pretrade_runner.step_market_snapshot(ctx, {})

        assert result.artifacts is not None
        assert result.artifacts["market_snapshot"]["skipped"] is True
    finally:
        session.close()


def test_pretrade_market_snapshot_records_missing_symbols(monkeypatch, tmp_path):
    session = _make_session()
    try:
        project = Project(name="pretrade-missing", description="")
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

        monkeypatch.setattr(pretrade_runner, "read_quotes", lambda *_args, **_kwargs: _quotes_payload(["SPY"]))
        monkeypatch.setattr(
            pretrade_runner,
            "_resolve_project_config",
            lambda _session, _pid: {"trade": {"market_snapshot_ttl_seconds": 30}},
        )
        monkeypatch.setattr(pretrade_runner, "resolve_bridge_root", lambda: tmp_path)
        monkeypatch.setattr(pretrade_runner, "_resolve_bridge_root", lambda: tmp_path)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        with pytest.raises(RuntimeError) as exc:
            pretrade_runner.step_market_snapshot(ctx, {})

        assert str(exc.value) == "market_snapshot_failed"
        assert step.artifacts is not None
        snapshot_artifacts = step.artifacts.get("market_snapshot")
        assert snapshot_artifacts is not None
        assert set(snapshot_artifacts.get("missing_symbols", [])) == {"AAPL"}
        assert snapshot_artifacts.get("stale_symbols") == []
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

        def _build_snapshot_symbols(_session, *, project_id, decision_snapshot_id=None, **_kwargs):
            assert decision_snapshot_id == snapshot_new.id
            return ["AAPL"]

        monkeypatch.setattr(pretrade_runner, "_build_snapshot_symbols", _build_snapshot_symbols)
        monkeypatch.setattr(pretrade_runner, "read_quotes", lambda *_args, **_kwargs: _quotes_payload(["AAPL"]))
        monkeypatch.setattr(
            pretrade_runner,
            "_resolve_project_config",
            lambda _session, _pid: {"trade": {"market_snapshot_ttl_seconds": 30}},
        )

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        result = pretrade_runner.step_market_snapshot(ctx, {})
        assert result.artifacts is not None
    finally:
        session.close()


def test_build_snapshot_symbols_uses_project_config_when_no_snapshot(monkeypatch):
    session = _make_session()
    try:
        project = Project(name="pretrade-config", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        monkeypatch.setattr(
            pretrade_runner,
            "_resolve_project_config",
            lambda *_args, **_kwargs: {"themes": [{"key": "tech", "weight": 1}]},
        )

        def _active_symbols_called(_session):
            raise AssertionError("collect_active_project_symbols should not be called here")

        monkeypatch.setattr(
            pretrade_runner, "collect_active_project_symbols", _active_symbols_called
        )
        monkeypatch.setattr(
            pretrade_runner,
            "collect_project_symbols",
            lambda _config: ["AAPL", "SPY"],
            raising=False,
        )

        symbols = pretrade_runner._build_snapshot_symbols(
            session,
            project_id=project.id,
            decision_snapshot_id=None,
        )

        assert symbols == ["AAPL", "SPY"]
    finally:
        session.close()


def test_market_snapshot_writes_watchlist_on_missing_quotes(monkeypatch, tmp_path):
    session = _make_session()
    try:
        project = Project(name="pretrade-watchlist", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "items.csv"
        items_path.write_text("symbol\nAAPL\nMSFT\n", encoding="utf-8")
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

        monkeypatch.setattr(pretrade_runner, "read_quotes", lambda *_args, **_kwargs: {"items": []})
        monkeypatch.setattr(
            pretrade_runner,
            "_resolve_project_config",
            lambda _session, _pid: {"trade": {"market_snapshot_ttl_seconds": 30}},
        )
        monkeypatch.setattr(
            pretrade_runner,
            "resolve_bridge_root",
            lambda: tmp_path,
        )

        try:
            pretrade_runner.step_market_snapshot(
                pretrade_runner.StepContext(session=session, run=run, step=step), {}
            )
        except RuntimeError:
            pass

        watchlist_path = tmp_path / "watchlist.json"
        assert watchlist_path.exists()
        payload = watchlist_path.read_text(encoding="utf-8")
        assert "AAPL" in payload and "MSFT" in payload
    finally:
        session.close()
