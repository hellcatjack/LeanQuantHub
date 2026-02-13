from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeFill, TradeRun
from app.services import ib_execution_backfill
from app.services.trade_orders import create_trade_order, update_trade_order_status


def _make_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_build_events_maps_ib_execution_to_manual_tag():
    candidate = ib_execution_backfill._CandidateOrder(
        order_id=3369,
        run_id=None,
        ib_order_id=5711,
        symbol="AMSC",
        side="SELL",
        tag="manual_3_1770992553631_0111-5m",
        status="SUBMITTED",
        submit_source="leader_command",
        submit_status="submitted",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    row = ib_execution_backfill._IBExecutionRow(
        order_id=5711,
        symbol="AMSC",
        side="SLD",
        shares=9.0,
        price=31.97,
        exec_id="0000e0d5.698ec3a1.01.01",
        time_raw="20260213  09:23:15",
    )

    events = ib_execution_backfill._build_events([candidate], [row])

    assert len(events) == 1
    event = events[0]
    assert event["tag"] == "manual_3_1770992553631_0111-5m"
    assert float(event["filled"]) == -9.0
    assert float(event["fill_price"]) == 31.97
    assert event["exec_id"] == "0000e0d5.698ec3a1.01.01"


def test_build_events_skips_side_mismatch():
    candidate = ib_execution_backfill._CandidateOrder(
        order_id=3369,
        run_id=None,
        ib_order_id=5711,
        symbol="AMSC",
        side="SELL",
        tag="manual_3_1770992553631_0111-5m",
        status="SUBMITTED",
        submit_source="leader_command",
        submit_status="submitted",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    row = ib_execution_backfill._IBExecutionRow(
        order_id=5711,
        symbol="AMSC",
        side="BUY",
        shares=9.0,
        price=31.97,
        exec_id="exec-side-mismatch",
        time_raw="20260213  09:23:15",
    )

    events = ib_execution_backfill._build_events([candidate], [row])
    assert events == []


def test_reconcile_direct_orders_with_ib_executions_recovers_low_conf_missing(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        order = create_trade_order(
            session,
            {
                "client_order_id": "manual_3_1770992553631_0111-5m",
                "symbol": "AMSC",
                "side": "SELL",
                "quantity": 9,
                "order_type": "LMT",
                "limit_price": 31.9,
                "params": {"source": "manual"},
            },
        ).order
        session.commit()
        update_trade_order_status(session, order, {"status": "SUBMITTED"})
        update_trade_order_status(
            session,
            order,
            {
                "status": "CANCELED",
                "params": {"event_source": "lean_open_orders", "sync_reason": "missing_from_open_orders"},
            },
        )
        order.ib_order_id = 5711
        session.commit()

        class _Settings:
            host = "127.0.0.1"
            port = 7497

        monkeypatch.setattr(ib_execution_backfill, "get_or_create_ib_settings", lambda _session: _Settings())
        monkeypatch.setattr(
            ib_execution_backfill,
            "_fetch_ib_executions",
            lambda **_kwargs: [
                ib_execution_backfill._IBExecutionRow(
                    order_id=5711,
                    symbol="AMSC",
                    side="SLD",
                    shares=9.0,
                    price=31.97,
                    exec_id="0000e0d5.698ec3a1.01.01",
                    time_raw="20260213  09:23:15",
                )
            ],
        )

        summary = ib_execution_backfill.reconcile_direct_orders_with_ib_executions(
            session,
            limit=50,
            min_query_interval_seconds=0,
            lookback_hours=12,
        )
        session.expire_all()
        refreshed = session.get(type(order), order.id)
        fills = session.query(TradeFill).filter(TradeFill.order_id == order.id).all()

        assert summary["candidates"] == 1
        assert summary["events_built"] == 1
        assert summary["processed"] == 1
        assert refreshed is not None
        assert refreshed.status == "FILLED"
        assert float(refreshed.filled_quantity or 0.0) == 9.0
        assert float(refreshed.avg_fill_price or 0.0) == 31.97
        assert len(fills) == 1
        assert fills[0].exec_id == "0000e0d5.698ec3a1.01.01"
    finally:
        session.close()


def test_reconcile_direct_orders_with_ib_executions_infers_canceled_when_missing(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        order = create_trade_order(
            session,
            {
                "client_order_id": "manual_7_1770993729739_x1",
                "symbol": "GSAT",
                "side": "SELL",
                "quantity": 5,
                "order_type": "LMT",
                "limit_price": 58.0,
                "params": {"source": "manual"},
            },
        ).order
        session.commit()
        update_trade_order_status(
            session,
            order,
            {
                "status": "SUBMITTED",
                "params": {
                    "submit_command": {
                        "source": "leader_command",
                        "status": "submitted",
                        "pending": False,
                    }
                },
            },
        )
        order.ib_order_id = 5836
        session.commit()

        class _Settings:
            host = "127.0.0.1"
            port = 7497

        monkeypatch.setattr(ib_execution_backfill, "get_or_create_ib_settings", lambda _session: _Settings())
        monkeypatch.setattr(ib_execution_backfill, "_fetch_ib_executions", lambda **_kwargs: [])

        summary = ib_execution_backfill.reconcile_direct_orders_with_ib_executions(
            session,
            limit=50,
            min_query_interval_seconds=0,
            lookback_hours=12,
            open_tags=set(),
            infer_canceled_missing=True,
            missing_cancel_min_age_seconds=0,
        )
        session.expire_all()
        refreshed = session.get(type(order), order.id)

        assert summary["candidates"] == 1
        assert summary["events_built"] == 0
        assert summary["canceled_inferred"] == 1
        assert refreshed is not None
        assert refreshed.status == "CANCELED"
    finally:
        session.close()


def test_reconcile_direct_orders_with_ib_executions_does_not_infer_canceled_when_open(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        order = create_trade_order(
            session,
            {
                "client_order_id": "manual_8_1770993729739_x2",
                "symbol": "TYL",
                "side": "SELL",
                "quantity": 1,
                "order_type": "LMT",
                "limit_price": 290.0,
                "params": {"source": "manual"},
            },
        ).order
        session.commit()
        update_trade_order_status(
            session,
            order,
            {
                "status": "SUBMITTED",
                "params": {
                    "submit_command": {
                        "source": "leader_command",
                        "status": "submitted",
                        "pending": False,
                    }
                },
            },
        )
        order.ib_order_id = 5839
        session.commit()

        class _Settings:
            host = "127.0.0.1"
            port = 7497

        monkeypatch.setattr(ib_execution_backfill, "get_or_create_ib_settings", lambda _session: _Settings())
        monkeypatch.setattr(ib_execution_backfill, "_fetch_ib_executions", lambda **_kwargs: [])

        summary = ib_execution_backfill.reconcile_direct_orders_with_ib_executions(
            session,
            limit=50,
            min_query_interval_seconds=0,
            lookback_hours=12,
            open_tags={order.client_order_id},
            infer_canceled_missing=True,
            missing_cancel_min_age_seconds=0,
        )
        session.expire_all()
        refreshed = session.get(type(order), order.id)

        assert summary["candidates"] == 1
        assert summary["canceled_inferred"] == 0
        assert refreshed is not None
        assert refreshed.status == "SUBMITTED"
    finally:
        session.close()


def test_reconcile_direct_orders_with_ib_executions_recovers_run_order_from_broker_fill(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        run = TradeRun(project_id=1, mode="paper", status="partial", params={"mode": "paper"})
        session.add(run)
        session.commit()
        session.refresh(run)

        order = create_trade_order(
            session,
            {
                "client_order_id": "oi_1107_24",
                "symbol": "SATS",
                "side": "BUY",
                "quantity": 3,
                "order_type": "MKT",
                "params": {"mode": "paper"},
            },
            run_id=run.id,
        ).order
        session.commit()
        update_trade_order_status(session, order, {"status": "SUBMITTED"})
        update_trade_order_status(
            session,
            order,
            {
                "status": "CANCELED",
                "params": {"event_source": "lean", "sync_reason": "execution_event_canceled"},
            },
        )
        order.ib_order_id = 6029
        session.commit()

        class _Settings:
            host = "127.0.0.1"
            port = 7497

        monkeypatch.setattr(ib_execution_backfill, "get_or_create_ib_settings", lambda _session: _Settings())
        monkeypatch.setattr(
            ib_execution_backfill,
            "_fetch_ib_executions",
            lambda **_kwargs: [
                ib_execution_backfill._IBExecutionRow(
                    order_id=6029,
                    symbol="SATS",
                    side="BOT",
                    shares=3.0,
                    price=109.16,
                    exec_id="00025b49.699074ef.01.01",
                    time_raw="20260213 09:52:54",
                )
            ],
        )

        summary = ib_execution_backfill.reconcile_direct_orders_with_ib_executions(
            session,
            limit=100,
            min_query_interval_seconds=0,
            lookback_hours=12,
            infer_canceled_missing=False,
        )
        session.expire_all()
        refreshed = session.get(type(order), order.id)
        fills = session.query(TradeFill).filter(TradeFill.order_id == order.id).all()

        assert summary["candidates"] == 1
        assert summary["events_built"] == 1
        assert summary["processed"] == 1
        assert refreshed is not None
        assert refreshed.status == "FILLED"
        assert float(refreshed.filled_quantity or 0.0) == 3.0
        assert len(fills) == 1
        assert fills[0].exec_id == "00025b49.699074ef.01.01"
    finally:
        session.close()


def test_reconcile_orders_with_ib_completed_status_terminalizes_run_cancel(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        run = TradeRun(project_id=1, mode="paper", status="running", params={"mode": "paper"})
        session.add(run)
        session.commit()
        session.refresh(run)

        order = create_trade_order(
            session,
            {
                "client_order_id": "oi_1108_31",
                "symbol": "GSAT",
                "side": "BUY",
                "quantity": 5,
                "order_type": "MKT",
                "params": {"mode": "paper"},
            },
            run_id=run.id,
        ).order
        session.commit()
        update_trade_order_status(session, order, {"status": "SUBMITTED"})
        order.ib_order_id = 7001
        session.commit()

        class _Settings:
            host = "127.0.0.1"
            port = 7497

        monkeypatch.setattr(ib_execution_backfill, "get_or_create_ib_settings", lambda _session: _Settings())
        monkeypatch.setattr(
            ib_execution_backfill,
            "_fetch_ib_completed_orders",
            lambda **_kwargs: [
                ib_execution_backfill._IBCompletedOrderRow(
                    order_id=7001,
                    perm_id=150000001,
                    symbol="GSAT",
                    side="BUY",
                    status="CANCELED",
                    completed_time_raw="20260213 10:16:27 America/New_York",
                    order_ref="oi_1108_31",
                    completed_status="Cancelled by Trader",
                )
            ],
        )

        summary = ib_execution_backfill.reconcile_orders_with_ib_completed_status(
            session,
            limit=200,
            min_query_interval_seconds=0,
            lookback_hours=12,
        )
        session.expire_all()
        refreshed = session.get(type(order), order.id)

        assert summary["candidates"] == 1
        assert summary["completed_rows_matched"] == 1
        assert summary["terminalized"] == 1
        assert refreshed is not None
        assert refreshed.status == "CANCELED"
        params = refreshed.params or {}
        assert params.get("sync_reason") == "ib_completed_order_canceled"
        assert params.get("event_source") == "ib_completed_orders"
    finally:
        session.close()


def test_reconcile_orders_with_ib_completed_status_skips_when_fill_exists(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        run = TradeRun(project_id=1, mode="paper", status="running", params={"mode": "paper"})
        session.add(run)
        session.commit()
        session.refresh(run)

        order = create_trade_order(
            session,
            {
                "client_order_id": "oi_1107_24",
                "symbol": "SATS",
                "side": "BUY",
                "quantity": 3,
                "order_type": "MKT",
                "params": {"mode": "paper"},
            },
            run_id=run.id,
        ).order
        session.commit()
        update_trade_order_status(session, order, {"status": "SUBMITTED"})
        order.ib_order_id = 6029
        session.commit()

        class _Settings:
            host = "127.0.0.1"
            port = 7497

        monkeypatch.setattr(ib_execution_backfill, "get_or_create_ib_settings", lambda _session: _Settings())
        monkeypatch.setattr(
            ib_execution_backfill,
            "_fetch_ib_completed_orders",
            lambda **_kwargs: [
                ib_execution_backfill._IBCompletedOrderRow(
                    order_id=6029,
                    perm_id=150000331,
                    symbol="SATS",
                    side="BUY",
                    status="FILLED",
                    completed_time_raw="20260213 09:52:54 America/New_York",
                    order_ref="oi_1107_24",
                    completed_status="Filled Size: 3",
                ),
                ib_execution_backfill._IBCompletedOrderRow(
                    order_id=6029,
                    perm_id=150000543,
                    symbol="SATS",
                    side="BUY",
                    status="CANCELED",
                    completed_time_raw="20260213 09:54:55 America/New_York",
                    order_ref="oi_1107_24",
                    completed_status="Cancelled by Trader",
                ),
            ],
        )

        summary = ib_execution_backfill.reconcile_orders_with_ib_completed_status(
            session,
            limit=200,
            min_query_interval_seconds=0,
            lookback_hours=12,
        )
        session.expire_all()
        refreshed = session.get(type(order), order.id)

        assert summary["candidates"] == 1
        assert summary["completed_rows_matched"] == 2
        assert summary["terminalized"] == 0
        assert summary["skipped_filled_hint"] == 1
        assert refreshed is not None
        assert refreshed.status == "SUBMITTED"
    finally:
        session.close()
