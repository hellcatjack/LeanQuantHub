from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeFill, TradeOrder
from app.services import lean_execution
from app.services.trade_orders import create_trade_order


def _make_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_apply_execution_events_updates_order(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        payload = {
            "client_order_id": "oi_0_0_123",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
        }
        result = create_trade_order(session, payload)
        session.commit()

        monkeypatch.setattr(lean_execution, "SessionLocal", Session, raising=False)

        events = [
            {
                "tag": "oi_0_0_123",
                "status": "Submitted",
                "order_id": 1001,
                "time": "2026-01-28T00:00:00Z",
            },
            {
                "tag": "oi_0_0_123",
                "status": "Filled",
                "filled": 1,
                "fill_price": 100.0,
                "exec_id": "exec-oi-123",
                "time": "2026-01-28T00:00:01Z",
            },
        ]
        lean_execution.apply_execution_events(events)

        verify_session = Session()
        try:
            refreshed = (
                verify_session.query(type(result.order))
                .filter_by(client_order_id="oi_0_0_123")
                .one()
            )
            assert refreshed.status == "FILLED"
            assert refreshed.filled_quantity == 1
            assert refreshed.avg_fill_price == 100.0
            assert refreshed.ib_order_id == 1001
        finally:
            verify_session.close()
    finally:
        session.close()


def test_apply_execution_events_clears_submit_pending(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        payload = {
            "client_order_id": "oi_0_0_pending",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "ADAPTIVE_LMT",
            "params": {
                "submit_command": {
                    "pending": True,
                    "command_id": "submit_order_123",
                    "requested_at": "2026-02-12T00:00:00Z",
                }
            },
        }
        create_trade_order(session, payload)
        session.commit()

        monkeypatch.setattr(lean_execution, "SessionLocal", Session, raising=False)

        events = [
            {
                "tag": "oi_0_0_pending",
                "status": "Submitted",
                "order_id": 1002,
                "time": "2026-01-28T00:00:00Z",
            },
            {
                "tag": "oi_0_0_pending",
                "status": "Filled",
                "filled": 1,
                "fill_price": 101.0,
                "exec_id": "exec-oi-pending",
                "time": "2026-01-28T00:00:01Z",
            },
        ]
        lean_execution.apply_execution_events(events)

        verify_session = Session()
        try:
            refreshed = verify_session.query(TradeOrder).filter_by(client_order_id="oi_0_0_pending").one()
            submit_meta = dict((refreshed.params or {}).get("submit_command") or {})
            assert refreshed.status == "FILLED"
            assert submit_meta.get("pending") is False
            assert submit_meta.get("status") == "submitted"
        finally:
            verify_session.close()
    finally:
        session.close()


def test_apply_execution_events_oi_fill_without_exec_id_keeps_submitted(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        payload = {
            "client_order_id": "oi_0_0_noexec",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "ADAPTIVE_LMT",
        }
        create_trade_order(session, payload)
        session.commit()

        monkeypatch.setattr(lean_execution, "SessionLocal", Session, raising=False)

        events = [
            {
                "tag": "oi_0_0_noexec",
                "status": "Submitted",
                "order_id": 1003,
                "time": "2026-01-28T00:00:00Z",
            },
            {
                "tag": "oi_0_0_noexec",
                "status": "Filled",
                "filled": 1,
                "fill_price": 101.0,
                # no exec_id -> low-confidence event, should not terminalize.
                "time": "2026-01-28T00:00:01Z",
            },
        ]
        lean_execution.apply_execution_events(events)

        verify_session = Session()
        try:
            refreshed = verify_session.query(TradeOrder).filter_by(client_order_id="oi_0_0_noexec").one()
            assert refreshed.status == "SUBMITTED"
            assert float(refreshed.filled_quantity or 0.0) == 0.0
            params = dict(refreshed.params or {})
            assert params.get("sync_reason") == "execution_fill_unconfirmed_no_exec_id"
            assert verify_session.query(TradeFill).count() == 0
        finally:
            verify_session.close()
    finally:
        session.close()


def test_apply_execution_events_manual_tag_fill_updates_direct_order(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        payload = {
            "client_order_id": "manual_3_1770992553631_0111-5m",
            "symbol": "AMSC",
            "side": "SELL",
            "quantity": 9,
            "order_type": "LMT",
            "limit_price": 31.5,
            "params": {"source": "manual", "mode": "paper"},
        }
        created = create_trade_order(session, payload).order
        session.commit()
        session.refresh(created)

        monkeypatch.setattr(lean_execution, "SessionLocal", Session, raising=False)

        events = [
            {
                "tag": str(created.client_order_id),
                "status": "Filled",
                "order_id": 5711,
                "filled": -9,
                "fill_price": 32.05,
                "exec_id": "exec-manual-5711",
                "time": "2026-02-13T14:22:36Z",
            }
        ]
        lean_execution.apply_execution_events(events)

        verify_session = Session()
        try:
            refreshed = verify_session.get(TradeOrder, created.id)
            assert refreshed.status == "FILLED"
            assert float(refreshed.filled_quantity or 0.0) == 9.0
            assert refreshed.ib_order_id == 5711
            params = dict(refreshed.params or {})
            assert params.get("sync_reason") == "execution_fill"
            fills = verify_session.query(TradeFill).filter(TradeFill.order_id == refreshed.id).all()
            assert len(fills) == 1
            assert fills[0].exec_id == "exec-manual-5711"
        finally:
            verify_session.close()
    finally:
        session.close()


def test_apply_execution_events_oi_fill_without_exec_id_run_scoped_path_fills(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        payload = {
            "client_order_id": "oi_1092_1",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "ADAPTIVE_LMT",
        }
        create_trade_order(session, payload)
        session.commit()

        monkeypatch.setattr(lean_execution, "SessionLocal", Session, raising=False)

        events = [
            {
                "tag": "oi_1092_1",
                "status": "Submitted",
                "order_id": 2001,
                "time": "2026-02-12T19:10:00.1363071Z",
                "_event_path": "/app/stocklean/artifacts/lean_bridge_runs/run_1092/execution_events.jsonl",
            },
            {
                "tag": "oi_1092_1",
                "status": "Filled",
                "filled": 1,
                "fill_price": 261.58,
                # no exec_id, but trusted run-scoped event path should still be applied.
                "time": "2026-02-12T19:10:00.2716725Z",
                "_event_path": "/app/stocklean/artifacts/lean_bridge_runs/run_1092/execution_events.jsonl",
            },
        ]
        lean_execution.apply_execution_events(events)

        verify_session = Session()
        try:
            refreshed = verify_session.query(TradeOrder).filter_by(client_order_id="oi_1092_1").one()
            assert refreshed.status == "FILLED"
            assert float(refreshed.filled_quantity or 0.0) == 1.0
            params = dict(refreshed.params or {})
            assert params.get("sync_reason") == "execution_fill_no_exec_id_run_scoped"
            assert params.get("event_exec_id") == "synthetic_no_exec_id"
            fills = verify_session.query(TradeFill).filter_by(order_id=refreshed.id).all()
            assert len(fills) == 1
            assert str(fills[0].exec_id).startswith("lean_no_exec:oi_1092_1:")
        finally:
            verify_session.close()
    finally:
        session.close()


def test_apply_execution_events_idempotent(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        payload = {
            "client_order_id": "oi_0_0_456",
            "symbol": "MSFT",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
        }
        result = create_trade_order(session, payload)
        session.commit()

        monkeypatch.setattr(lean_execution, "SessionLocal", Session, raising=False)

        events = [
            {
                "tag": "oi_0_0_456",
                "status": "Submitted",
                "order_id": 2001,
                "time": "2026-01-28T00:00:00Z",
            },
            {
                "tag": "oi_0_0_456",
                "status": "Filled",
                "filled": 1,
                "fill_price": 250.0,
                "exec_id": "exec-oi-456",
                "time": "2026-01-28T00:00:01Z",
            },
        ]
        lean_execution.apply_execution_events(events)
        lean_execution.apply_execution_events(events)

        verify_session = Session()
        try:
            refreshed = (
                verify_session.query(TradeOrder)
                .filter_by(client_order_id="oi_0_0_456")
                .one()
            )
            assert refreshed.status == "FILLED"
            assert refreshed.filled_quantity == 1
            assert refreshed.avg_fill_price == 250.0
            assert refreshed.ib_order_id == 2001
            assert verify_session.query(TradeFill).count() == 1
        finally:
            verify_session.close()
    finally:
        session.close()


def test_apply_execution_events_idempotent_with_fractional_time(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        payload = {
            "client_order_id": "oi_0_0_789",
            "symbol": "NVDA",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
        }
        result = create_trade_order(session, payload)
        session.commit()

        monkeypatch.setattr(lean_execution, "SessionLocal", Session, raising=False)

        events = [
            {
                "tag": "oi_0_0_789",
                "status": "Submitted",
                "order_id": 3001,
                "time": "2026-01-28T00:00:00.1234567Z",
            },
            {
                "tag": "oi_0_0_789",
                "status": "Filled",
                "filled": 1,
                "fill_price": 500.0,
                "exec_id": "exec-oi-789",
                "time": "2026-01-28T00:00:01.1234567Z",
            },
        ]
        lean_execution.apply_execution_events(events)
        lean_execution.apply_execution_events(events)

        verify_session = Session()
        try:
            refreshed = (
                verify_session.query(TradeOrder)
                .filter_by(client_order_id="oi_0_0_789")
                .one()
            )
            assert refreshed.status == "FILLED"
            assert refreshed.filled_quantity == 1
            assert refreshed.avg_fill_price == 500.0
            assert refreshed.ib_order_id == 3001
            assert verify_session.query(TradeFill).count() == 1
        finally:
            verify_session.close()
    finally:
        session.close()


def test_apply_execution_events_direct_sell_negative_fill(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        payload = {
            "client_order_id": "manual-sell-1",
            "symbol": "AMSC",
            "side": "SELL",
            "quantity": 2,
            "order_type": "MKT",
        }
        result = create_trade_order(session, payload)
        session.commit()

        monkeypatch.setattr(lean_execution, "SessionLocal", Session, raising=False)

        events = [
            {
                "tag": f"direct:{result.order.id}",
                "status": "Submitted",
                "order_id": 4001,
                "time": "2026-02-11T10:27:11Z",
            },
            {
                "tag": f"direct:{result.order.id}",
                "status": "Filled",
                "filled": -2,
                "fill_price": 14.5,
                "time": "2026-02-11T10:27:14Z",
            },
        ]
        lean_execution.apply_execution_events(events)
        lean_execution.apply_execution_events(events)

        verify_session = Session()
        try:
            refreshed = verify_session.query(TradeOrder).filter_by(id=result.order.id).one()
            assert refreshed.status == "FILLED"
            assert refreshed.filled_quantity == 2
            assert refreshed.avg_fill_price == 14.5
            assert refreshed.ib_order_id == 4001
            fills = verify_session.query(TradeFill).filter_by(order_id=result.order.id).all()
            assert len(fills) == 1
            assert fills[0].fill_quantity == 2
        finally:
            verify_session.close()
    finally:
        session.close()


def test_apply_fill_to_order_handles_negative_historical_filled_quantity():
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        payload = {
            "client_order_id": "edge-negative-filled",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
        }
        result = create_trade_order(session, payload)
        order = result.order
        order.status = "PARTIAL"
        order.filled_quantity = -1
        order.avg_fill_price = 100.0
        session.commit()

        lean_execution._apply_fill_to_order(
            session,
            order,
            fill_qty=1,
            fill_price=101.0,
            fill_time=datetime(2026, 2, 11, 16, 50, 0, tzinfo=timezone.utc),
            exec_id="edge-negative-filled-1",
        )
        session.commit()
        session.refresh(order)

        assert order.status == "FILLED"
        assert order.filled_quantity == 1
        assert order.avg_fill_price == 101.0
    finally:
        session.close()


def test_apply_execution_events_canceled_event_overwrites_low_conf_sync_reason(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        payload = {
            "client_order_id": "oi_0_0_cancel_recover",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
        }
        result = create_trade_order(session, payload)
        order = result.order
        order.status = "CANCELED"
        order.params = {
            "event_tag": "oi_0_0_cancel_recover",
            "event_source": "lean_open_orders",
            "event_status": "CANCELED",
            "sync_reason": "missing_from_open_orders",
        }
        session.commit()

        monkeypatch.setattr(lean_execution, "SessionLocal", Session, raising=False)

        events = [
            {
                "tag": "oi_0_0_cancel_recover",
                "status": "Canceled",
                "order_id": 5001,
                "time": "2026-02-13T02:02:14Z",
            },
        ]
        lean_execution.apply_execution_events(events)

        verify_session = Session()
        try:
            refreshed = verify_session.query(TradeOrder).filter_by(id=order.id).one()
            params = dict(refreshed.params or {})
            assert refreshed.status == "CANCELED"
            assert refreshed.ib_order_id == 5001
            assert params.get("event_source") == "lean"
            assert params.get("event_status") == "CANCELED"
            assert params.get("sync_reason") == "execution_event_canceled"
        finally:
            verify_session.close()
    finally:
        session.close()


def test_apply_execution_events_submitted_recovery_ignores_stale_event_time(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        payload = {
            "client_order_id": "oi_0_0_submitted_recovery_stale",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
        }
        result = create_trade_order(session, payload)
        order = result.order
        order.status = "CANCELED"
        order.params = {
            "event_tag": "oi_0_0_submitted_recovery_stale",
            "event_source": "lean_open_orders",
            "event_status": "CANCELED",
            "sync_reason": "missing_from_open_orders",
        }
        order.updated_at = datetime.now(timezone.utc)
        session.commit()

        monkeypatch.setattr(lean_execution, "SessionLocal", Session, raising=False)

        stale_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        events = [
            {
                "tag": "oi_0_0_submitted_recovery_stale",
                "status": "Submitted",
                "order_id": 6001,
                "time": stale_time,
            },
        ]
        lean_execution.apply_execution_events(events)

        verify_session = Session()
        try:
            refreshed = verify_session.query(TradeOrder).filter_by(id=order.id).one()
            params = dict(refreshed.params or {})
            assert refreshed.status == "CANCELED"
            assert params.get("sync_reason") == "missing_from_open_orders"
            assert refreshed.ib_order_id == 6001
        finally:
            verify_session.close()
    finally:
        session.close()


def test_apply_execution_events_submitted_recovery_accepts_fresh_event_time(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        payload = {
            "client_order_id": "oi_0_0_submitted_recovery_fresh",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
        }
        result = create_trade_order(session, payload)
        order = result.order
        order.status = "CANCELED"
        order.params = {
            "event_tag": "oi_0_0_submitted_recovery_fresh",
            "event_source": "lean_open_orders",
            "event_status": "CANCELED",
            "sync_reason": "missing_from_open_orders",
        }
        order.updated_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        session.commit()

        monkeypatch.setattr(lean_execution, "SessionLocal", Session, raising=False)

        fresh_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        events = [
            {
                "tag": "oi_0_0_submitted_recovery_fresh",
                "status": "Submitted",
                "order_id": 6002,
                "time": fresh_time,
            },
        ]
        lean_execution.apply_execution_events(events)

        verify_session = Session()
        try:
            refreshed = verify_session.query(TradeOrder).filter_by(id=order.id).one()
            params = dict(refreshed.params or {})
            assert refreshed.status == "SUBMITTED"
            assert params.get("sync_reason") == "execution_event_submitted_recovered"
            assert refreshed.ib_order_id == 6002
        finally:
            verify_session.close()
    finally:
        session.close()
