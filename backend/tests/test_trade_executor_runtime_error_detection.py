from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, TradeOrder, TradeRun
from app.services import trade_executor


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_detects_warmup_submit_blocked_runtime_error(monkeypatch, tmp_path):
    log_path = tmp_path / "LeanBridgeExecutionAlgorithm-log.txt"
    log_path.write_text(
        "\n".join(
            [
                "2026-02-12 17:49:53 TRACE:: Using /app/stocklean/artifacts/lean_execution/trade_run_1099.json as configuration file",
                "2026-02-12 17:50:01 ERROR:: This operation is not allowed in Initialize or during warm up: OrderRequest.Submit.",
                "2026-02-12 17:50:01 LEAN_BRIDGE_INTENT: path=/app/stocklean/artifacts/order_intents/order_intent_run_1099.json requests=31",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(trade_executor, "_resolve_lean_execution_log_path", lambda: log_path, raising=False)

    assert trade_executor._lean_submit_blocked_during_warmup(1099) is True


def test_runtime_error_rewrites_low_conf_canceled_to_rejected(monkeypatch, tmp_path):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p-runtime", description=""))
        session.commit()

        run = TradeRun(
            project_id=1,
            decision_snapshot_id=1,
            mode="paper",
            status="running",
            params={"lean_execution": {"output_dir": str(tmp_path / "run_1"), "source": "short_lived"}},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        order_low_conf_cancel = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1",
            symbol="ALB",
            side="BUY",
            quantity=1,
            order_type="LMT",
            status="CANCELED",
            params={"sync_reason": "missing_from_open_orders", "event_source": "lean_open_orders"},
        )
        order_with_ib_cancel = TradeOrder(
            run_id=run.id,
            client_order_id="oi_2",
            symbol="AMAT",
            side="BUY",
            quantity=1,
            order_type="LMT",
            status="CANCELED",
            ib_order_id=1001,
            params={"sync_reason": "missing_from_open_orders", "event_source": "lean_open_orders"},
        )
        order_submitted = TradeOrder(
            run_id=run.id,
            client_order_id="oi_3",
            symbol="AMSC",
            side="BUY",
            quantity=1,
            order_type="LMT",
            status="SUBMITTED",
            params={},
        )
        session.add_all([order_low_conf_cancel, order_with_ib_cancel, order_submitted])
        session.commit()

        monkeypatch.setattr(trade_executor, "_lean_submit_blocked_during_warmup", lambda *_args, **_kwargs: True, raising=False)
        monkeypatch.setattr(trade_executor, "_resolve_bridge_root", lambda: tmp_path, raising=False)
        monkeypatch.setattr(trade_executor, "_reconcile_submit_command_results", lambda *_args, **_kwargs: None, raising=False)
        monkeypatch.setattr(trade_executor, "read_open_orders", lambda *_args, **_kwargs: {"items": []}, raising=False)
        monkeypatch.setattr(trade_executor, "read_positions", lambda *_args, **_kwargs: {"items": []}, raising=False)
        monkeypatch.setattr(trade_executor, "sync_trade_orders_from_open_orders", lambda *_args, **_kwargs: None, raising=False)
        monkeypatch.setattr(trade_executor, "reconcile_run_with_positions", lambda *_args, **_kwargs: None, raising=False)
        monkeypatch.setattr(
            trade_executor,
            "_collect_timed_out_submit_pending_orders",
            lambda *_args, **_kwargs: {"timed_out": 0, "active": 0},
            raising=False,
        )
        monkeypatch.setattr(trade_executor, "_pid_alive", lambda *_args, **_kwargs: False, raising=False)
        monkeypatch.setattr(trade_executor, "_terminate_pid", lambda *_args, **_kwargs: False, raising=False)
        monkeypatch.setattr(trade_executor, "record_audit", lambda *_args, **_kwargs: None, raising=False)

        assert trade_executor.refresh_trade_run_status(session, run) is True
        session.refresh(run)
        session.refresh(order_low_conf_cancel)
        session.refresh(order_with_ib_cancel)
        session.refresh(order_submitted)

        assert run.status == "failed"
        assert run.message == "execution_error:submit_during_warmup"
        summary = dict((run.params or {}).get("completion_summary") or {})
        assert summary.get("rejected") == 2
        assert summary.get("cancelled") == 1
        assert order_low_conf_cancel.status == "REJECTED"
        assert order_low_conf_cancel.rejected_reason == "OrderRequest.Submit blocked during warmup/initialize"
        assert order_with_ib_cancel.status == "CANCELED"
        assert order_submitted.status == "REJECTED"
    finally:
        session.close()
