from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeOrder, TradeRun


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_sync_trade_orders_from_open_orders_marks_missing_as_canceled():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        run = TradeRun(project_id=1, decision_snapshot_id=1, status="running", mode="paper", params={})
        session.add(run)
        session.commit()

        order = TradeOrder(
            run_id=run.id,
            client_order_id="1:AAPL:BUY:1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={"event_tag": "oi_1_1"},
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [],
            "refreshed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper")

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "CANCELED"
        assert summary["updated"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_keeps_open_when_tag_present():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        run = TradeRun(project_id=1, decision_snapshot_id=1, status="running", mode="paper", params={})
        session.add(run)
        session.commit()

        order = TradeOrder(
            run_id=run.id,
            client_order_id="1:AAPL:BUY:1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={"event_tag": "oi_1_1"},
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_1", "symbol": "AAPL"}],
            "refreshed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper")

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "SUBMITTED"
        assert summary["updated"] == 0
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_respects_mode_filter():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        paper_run = TradeRun(project_id=1, decision_snapshot_id=1, status="running", mode="paper", params={})
        live_run = TradeRun(project_id=1, decision_snapshot_id=1, status="running", mode="live", params={})
        session.add_all([paper_run, live_run])
        session.commit()

        paper_order = TradeOrder(
            run_id=paper_run.id,
            client_order_id="1:AAPL:BUY:1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={"event_tag": "oi_1_1"},
        )
        live_order = TradeOrder(
            run_id=live_run.id,
            client_order_id="2:MSFT:BUY:1",
            symbol="MSFT",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={"event_tag": "oi_2_1"},
        )
        session.add_all([paper_order, live_order])
        session.commit()

        open_orders = {
            "items": [],
            "refreshed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper")

        assert session.get(TradeOrder, paper_order.id).status == "CANCELED"
        assert session.get(TradeOrder, live_order.id).status == "SUBMITTED"
        assert summary["updated"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_skips_when_snapshot_stale():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        run = TradeRun(project_id=1, decision_snapshot_id=1, status="running", mode="paper", params={})
        session.add(run)
        session.commit()

        order = TradeOrder(
            run_id=run.id,
            client_order_id="1:AAPL:BUY:1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={"event_tag": "oi_1_1"},
        )
        session.add(order)
        session.commit()

        open_orders = {"items": [], "stale": True}
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper")

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "SUBMITTED"
        assert summary["updated"] == 0
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_can_cancel_new_when_enabled():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        now = datetime.now(timezone.utc)
        run = TradeRun(project_id=1, decision_snapshot_id=1, status="running", mode="paper", params={})
        session.add(run)
        session.commit()

        order = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="NEW",
            created_at=now - timedelta(seconds=120),
            params={"event_tag": "oi_1_1"},
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(
            session, open_orders, mode="paper", run_id=run.id, include_new=True, now=now
        )

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "CANCELED"
        assert summary["updated"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_can_promote_new_to_submitted_when_open():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        run = TradeRun(project_id=1, decision_snapshot_id=1, status="running", mode="paper", params={})
        session.add(run)
        session.commit()

        order = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="NEW",
            params={"event_tag": "oi_1_1"},
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_1", "symbol": "AAPL"}],
            "refreshed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(
            session, open_orders, mode="paper", run_id=run.id, include_new=True
        )

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "SUBMITTED"
        assert summary["updated"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_does_not_cancel_recent_new_orders():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        now = datetime.now(timezone.utc)
        run = TradeRun(project_id=1, decision_snapshot_id=1, status="running", mode="paper", params={})
        session.add(run)
        session.commit()

        order = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="NEW",
            created_at=now,
            params={"event_tag": "oi_1_1"},
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(
            session, open_orders, mode="paper", run_id=run.id, include_new=True, now=now
        )

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "NEW"
        assert summary["updated"] == 0
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_recovers_canceled_when_tag_present():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        now = datetime.now(timezone.utc)
        run = TradeRun(project_id=1, decision_snapshot_id=1, status="running", mode="paper", params={})
        session.add(run)
        session.commit()

        order = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="CANCELED",
            created_at=now - timedelta(seconds=120),
            params={"event_tag": "oi_1_1"},
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_1", "symbol": "AAPL", "status": "Submitted"}],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(
            session, open_orders, mode="paper", run_id=run.id, include_new=True, now=now
        )

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "SUBMITTED"
        assert summary["updated"] == 1
    finally:
        session.close()
