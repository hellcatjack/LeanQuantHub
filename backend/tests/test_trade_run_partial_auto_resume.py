from __future__ import annotations

from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, DecisionSnapshot, Project, TradeOrder, TradeRun, TradeSettings
from app.services import trade_executor


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def _seed_project_snapshot(session):
    project = Project(name="p-auto-resume", description="")
    session.add(project)
    session.commit()
    session.refresh(project)

    snapshot = DecisionSnapshot(project_id=project.id, status="success", items_path="/tmp/decision-items.csv")
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return project, snapshot


def test_refresh_trade_run_status_auto_resumes_partial_remaining(monkeypatch):
    session = _make_session()
    try:
        session.add(TradeSettings(risk_defaults={}, execution_data_source="lean", auto_recovery={}))
        session.commit()
        project, snapshot = _seed_project_snapshot(session)

        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            mode="paper",
            status="running",
            params={"strategy_snapshot": {"backtest_link_status": "current_project"}},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        session.add_all(
            [
                TradeOrder(
                    run_id=run.id,
                    client_order_id="oi_auto_1",
                    symbol="AAA",
                    side="BUY",
                    quantity=1,
                    order_type="MKT",
                    status="FILLED",
                ),
                TradeOrder(
                    run_id=run.id,
                    client_order_id="oi_auto_2",
                    symbol="BBB",
                    side="BUY",
                    quantity=1,
                    order_type="MKT",
                    status="SKIPPED",
                ),
            ]
        )
        session.commit()

        captured: dict[str, object] = {}

        monkeypatch.setattr(trade_executor, "read_open_orders", lambda *_a, **_k: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "read_positions", lambda *_a, **_k: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "sync_trade_orders_from_open_orders", lambda *_a, **_k: {})
        monkeypatch.setattr(trade_executor, "ingest_execution_events", lambda *_a, **_k: {})
        monkeypatch.setattr(trade_executor, "_reconcile_submit_command_results", lambda *_a, **_k: 0)
        monkeypatch.setattr(trade_executor, "reconcile_run_with_positions", lambda *_a, **_k: {"reconciled": 0})
        monkeypatch.setattr(trade_executor, "_lean_no_orders_submitted", lambda *_a, **_k: False)

        def _fake_execute(child_run_id, *, dry_run=False, force=False, risk_off_drill=False):
            captured["child_run_id"] = child_run_id
            captured["dry_run"] = dry_run
            captured["force"] = force
            return trade_executor.TradeExecutionResult(
                run_id=child_run_id,
                status="running",
                filled=0,
                cancelled=0,
                rejected=0,
                skipped=0,
                message="submitted_leader",
                dry_run=False,
            )

        monkeypatch.setattr(trade_executor, "execute_trade_run", _fake_execute, raising=False)

        changed = trade_executor.refresh_trade_run_status(session, run)

        assert changed is True
        session.refresh(run)
        assert run.status == "partial"
        auto_resume = dict((run.params or {}).get("auto_resume") or {})
        child_run_id = auto_resume.get("child_run_id")
        assert child_run_id
        assert captured.get("child_run_id") == child_run_id
        child = session.get(TradeRun, int(child_run_id))
        assert child is not None
        child_params = child.params if isinstance(child.params, dict) else {}
        assert child_params.get("auto_resume_parent_run_id") == run.id
        assert child_params.get("auto_resume_attempt") == 1
        assert child_params.get("auto_resume_reason") == "partial_remaining"
    finally:
        session.close()


def test_refresh_trade_run_status_does_not_auto_resume_partial_with_rejections(monkeypatch):
    session = _make_session()
    try:
        session.add(TradeSettings(risk_defaults={}, execution_data_source="lean", auto_recovery={}))
        session.commit()
        project, snapshot = _seed_project_snapshot(session)

        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            mode="paper",
            status="running",
            params={},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        session.add_all(
            [
                TradeOrder(
                    run_id=run.id,
                    client_order_id="oi_auto_r1",
                    symbol="AAA",
                    side="BUY",
                    quantity=1,
                    order_type="MKT",
                    status="FILLED",
                ),
                TradeOrder(
                    run_id=run.id,
                    client_order_id="oi_auto_r2",
                    symbol="BBB",
                    side="BUY",
                    quantity=1,
                    order_type="MKT",
                    status="REJECTED",
                ),
            ]
        )
        session.commit()

        execute_called = {"value": False}

        monkeypatch.setattr(trade_executor, "read_open_orders", lambda *_a, **_k: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "read_positions", lambda *_a, **_k: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "sync_trade_orders_from_open_orders", lambda *_a, **_k: {})
        monkeypatch.setattr(trade_executor, "ingest_execution_events", lambda *_a, **_k: {})
        monkeypatch.setattr(trade_executor, "_reconcile_submit_command_results", lambda *_a, **_k: 0)
        monkeypatch.setattr(trade_executor, "reconcile_run_with_positions", lambda *_a, **_k: {"reconciled": 0})
        monkeypatch.setattr(trade_executor, "_lean_no_orders_submitted", lambda *_a, **_k: False)
        monkeypatch.setattr(
            trade_executor,
            "execute_trade_run",
            lambda *_a, **_k: execute_called.update({"value": True}),
            raising=False,
        )

        changed = trade_executor.refresh_trade_run_status(session, run)

        assert changed is True
        session.refresh(run)
        assert run.status == "partial"
        assert execute_called["value"] is False
        assert "auto_resume" not in (run.params or {})
        child_runs = session.query(TradeRun).filter(TradeRun.project_id == project.id, TradeRun.id != run.id).all()
        assert child_runs == []
    finally:
        session.close()


def test_partial_auto_resume_reuses_existing_child_when_parent_metadata_lags(monkeypatch):
    session = _make_session()
    try:
        session.add(TradeSettings(risk_defaults={}, execution_data_source="lean", auto_recovery={}))
        session.commit()
        project, snapshot = _seed_project_snapshot(session)

        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            mode="paper",
            status="partial",
            params={"strategy_snapshot": {"backtest_link_status": "current_project"}},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        existing_child = TradeRun(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            mode="paper",
            status="running",
            params={
                "auto_resume_parent_run_id": run.id,
                "auto_resume_root_run_id": run.id,
                "auto_resume_attempt": 1,
                "auto_resume_reason": "partial_remaining",
            },
        )
        session.add(existing_child)
        session.commit()
        session.refresh(existing_child)

        execute_called = {"value": False}
        monkeypatch.setattr(
            trade_executor,
            "execute_trade_run",
            lambda *_a, **_k: execute_called.update({"value": True}),
            raising=False,
        )

        child_run_id = trade_executor._maybe_auto_resume_partial_run(
            session,
            run,
            summary={"total": 2, "filled": 1, "cancelled": 1, "rejected": 0, "skipped": 0},
        )

        assert child_run_id == existing_child.id
        assert execute_called["value"] is False
        child_runs = (
            session.query(TradeRun)
            .filter(TradeRun.project_id == project.id, TradeRun.id != run.id)
            .order_by(TradeRun.id)
            .all()
        )
        assert [child.id for child in child_runs] == [existing_child.id]
        session.refresh(run)
        auto_resume = dict((run.params or {}).get("auto_resume") or {})
        assert auto_resume.get("child_run_id") == existing_child.id
        assert auto_resume.get("reused_existing") is True
    finally:
        session.close()


def test_partial_auto_resume_marks_child_blocked_when_execute_lock_busy(monkeypatch):
    session = _make_session()
    try:
        session.add(TradeSettings(risk_defaults={}, execution_data_source="lean", auto_recovery={}))
        session.commit()
        project, snapshot = _seed_project_snapshot(session)

        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            mode="paper",
            status="running",
            params={},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        session.add_all(
            [
                TradeOrder(
                    run_id=run.id,
                    client_order_id="oi_lock_1",
                    symbol="AAA",
                    side="BUY",
                    quantity=1,
                    order_type="MKT",
                    status="FILLED",
                ),
                TradeOrder(
                    run_id=run.id,
                    client_order_id="oi_lock_2",
                    symbol="BBB",
                    side="BUY",
                    quantity=1,
                    order_type="MKT",
                    status="CANCELED",
                ),
            ]
        )
        session.commit()

        monkeypatch.setattr(trade_executor, "read_open_orders", lambda *_a, **_k: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "read_positions", lambda *_a, **_k: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "sync_trade_orders_from_open_orders", lambda *_a, **_k: {})
        monkeypatch.setattr(trade_executor, "ingest_execution_events", lambda *_a, **_k: {})
        monkeypatch.setattr(trade_executor, "_reconcile_submit_command_results", lambda *_a, **_k: 0)
        monkeypatch.setattr(trade_executor, "reconcile_run_with_positions", lambda *_a, **_k: {"reconciled": 0})
        monkeypatch.setattr(trade_executor, "_lean_no_orders_submitted", lambda *_a, **_k: False)

        def _raise_lock_busy(*_a, **_k):
            raise RuntimeError("trade_execution_lock_busy")

        monkeypatch.setattr(trade_executor, "execute_trade_run", _raise_lock_busy, raising=False)

        changed = trade_executor.refresh_trade_run_status(session, run)

        assert changed is True
        session.refresh(run)
        auto_resume = dict((run.params or {}).get("auto_resume") or {})
        child_run_id = auto_resume.get("child_run_id")
        assert child_run_id
        assert auto_resume.get("execute_error") == "trade_execution_lock_busy"
        child = session.get(TradeRun, int(child_run_id))
        assert child is not None
        assert child.status == "blocked"
        assert child.message == "trade_execution_lock_busy"
        assert child.ended_at is not None
    finally:
        session.close()
