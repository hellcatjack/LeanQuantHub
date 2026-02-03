from datetime import datetime
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import (
    AutoWeeklyJob,
    Base,
    DecisionSnapshot,
    PreTradeRun,
    PreTradeStep,
    TradeOrder,
    TradeRun,
)
from app.services.pipeline_aggregator import build_pipeline_trace, list_pipeline_runs


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_list_pipeline_runs_project_scoped():
    session = _make_session()
    session.add_all(
        [
            PreTradeRun(project_id=1, status="success"),
            PreTradeRun(project_id=2, status="success"),
            TradeRun(project_id=1, status="queued", mode="paper", params={"source": "manual"}),
        ]
    )
    session.commit()

    runs = list_pipeline_runs(session, project_id=1)
    trace_ids = {item["trace_id"] for item in runs}
    assert "pretrade:1" in trace_ids
    assert "trade:1" in trace_ids
    assert all(item["project_id"] == 1 for item in runs)


def test_list_includes_auto_weekly():
    session = _make_session()
    session.add(AutoWeeklyJob(project_id=1, status="running"))
    session.commit()

    runs = list_pipeline_runs(session, project_id=1)
    assert any(item["trace_id"].startswith("auto:") for item in runs)


def test_pretrade_trace_includes_snapshot_and_trade():
    session = _make_session()
    run = PreTradeRun(project_id=1, status="success")
    session.add(run)
    session.commit()

    snapshot = DecisionSnapshot(project_id=1, status="success")
    session.add(snapshot)
    session.commit()

    trade_run = TradeRun(
        project_id=1,
        decision_snapshot_id=snapshot.id,
        status="queued",
        mode="paper",
    )
    session.add(trade_run)
    session.commit()

    step = PreTradeStep(
        run_id=run.id,
        step_key="decision_snapshot",
        step_order=1,
        status="success",
        artifacts={"decision_snapshot_id": snapshot.id, "trade_run_id": trade_run.id},
    )
    session.add(step)
    session.commit()

    order = TradeOrder(
        run_id=trade_run.id,
        client_order_id="run-1-SPY-BUY",
        symbol="SPY",
        side="BUY",
        quantity=1,
        order_type="MKT",
        status="NEW",
    )
    session.add(order)
    session.commit()

    detail = build_pipeline_trace(session, trace_id=f"pretrade:{run.id}")
    event_types = {event["task_type"] for event in detail["events"]}
    assert "pretrade_run" in event_types
    assert "pretrade_step" in event_types
    assert "decision_snapshot" in event_types
    assert "trade_run" in event_types
    assert "trade_order" in event_types


def test_list_pipeline_runs_sorted_desc():
    session = _make_session()
    session.add_all(
        [
            PreTradeRun(project_id=1, status="success", created_at=datetime(2024, 1, 1)),
            TradeRun(
                project_id=1,
                status="queued",
                mode="paper",
                created_at=datetime(2024, 1, 2),
            ),
            AutoWeeklyJob(project_id=1, status="running", created_at=datetime(2024, 1, 3)),
        ]
    )
    session.commit()

    runs = list_pipeline_runs(session, project_id=1)
    assert [item["trace_id"] for item in runs] == ["auto:1", "trade:1", "pretrade:1"]


def test_pretrade_trace_sorted_by_time():
    session = _make_session()
    run = PreTradeRun(project_id=1, status="success", started_at=datetime(2024, 1, 1, 10, 0, 0))
    session.add(run)
    session.commit()

    snapshot = DecisionSnapshot(
        project_id=1, status="success", started_at=datetime(2024, 1, 1, 12, 0, 0)
    )
    session.add(snapshot)
    session.commit()

    trade_run = TradeRun(
        project_id=1,
        decision_snapshot_id=snapshot.id,
        status="queued",
        mode="paper",
        started_at=datetime(2024, 1, 1, 9, 0, 0),
    )
    session.add(trade_run)
    session.commit()

    step = PreTradeStep(
        run_id=run.id,
        step_key="decision_snapshot",
        step_order=1,
        status="success",
        started_at=datetime(2024, 1, 1, 11, 0, 0),
        artifacts={"decision_snapshot_id": snapshot.id, "trade_run_id": trade_run.id},
    )
    session.add(step)
    session.commit()

    order = TradeOrder(
        run_id=trade_run.id,
        client_order_id="run-1-SPY-BUY",
        symbol="SPY",
        side="BUY",
        quantity=1,
        order_type="MKT",
        status="NEW",
        created_at=datetime(2024, 1, 1, 9, 30, 0),
    )
    session.add(order)
    session.commit()

    detail = build_pipeline_trace(session, trace_id=f"pretrade:{run.id}")
    assert [event["event_id"] for event in detail["events"]] == [
        f"trade_run:{trade_run.id}",
        f"trade_order:{order.id}",
        f"pretrade_run:{run.id}",
        f"pretrade_step:{step.id}",
        f"decision_snapshot:{snapshot.id}",
    ]


def test_pipeline_event_contains_audit_fields():
    session = _make_session()
    run = PreTradeRun(project_id=1, status="failed", message="pretrade_failed")
    session.add(run)
    session.commit()

    detail = build_pipeline_trace(session, trace_id=f"pretrade:{run.id}")
    event = next(item for item in detail["events"] if item["task_type"] == "pretrade_run")
    assert "error_code" in event
    assert "log_path" in event
    assert "params_snapshot" in event
    assert "artifact_paths" in event
    assert "tags" in event
    assert "parent_id" in event
