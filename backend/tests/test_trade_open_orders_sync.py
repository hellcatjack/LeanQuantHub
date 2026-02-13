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


def test_sync_trade_orders_from_open_orders_defers_missing_submitted_before_grace():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        now = datetime.now(timezone.utc)
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
            "items": [{"tag": "oi_1_2", "symbol": "MSFT"}],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper", now=now)

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "SUBMITTED"
        assert (refreshed.params or {}).get("open_orders_missing_since")
        assert summary["updated"] == 0
        assert summary["skipped_missing_grace"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_keeps_missing_submitted_unconfirmed_after_grace():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        now = datetime.now(timezone.utc)
        order = TradeOrder(
            run_id=None,
            client_order_id="1:AAPL:BUY:1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={
                "event_tag": "oi_1_1",
                "open_orders_missing_since": (now - timedelta(seconds=120)).isoformat().replace("+00:00", "Z"),
            },
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_2", "symbol": "MSFT"}],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper", now=now)

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "SUBMITTED"
        params = dict(refreshed.params or {})
        assert params.get("open_orders_missing_since")
        assert params.get("open_orders_missing_last_seen")
        assert params.get("open_orders_missing_unconfirmed") is True
        assert summary["updated"] == 0
        assert summary["skipped_missing_unconfirmed"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_marks_missing_submitted_canceled_after_unconfirmed_timeout():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        now = datetime.now(timezone.utc)
        order = TradeOrder(
            run_id=None,
            client_order_id="1:AAPL:BUY:1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={
                "event_tag": "oi_1_1",
                "open_orders_missing_since": (now - timedelta(seconds=360)).isoformat().replace("+00:00", "Z"),
            },
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_2", "symbol": "MSFT"}],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper", now=now)

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "CANCELED"
        params = dict(refreshed.params or {})
        assert params.get("sync_reason") == "missing_from_open_orders"
        assert params.get("open_orders_missing_unconfirmed") is True
        assert summary["updated"] == 1
        assert summary["updated_missing_to_canceled"] == 1
        assert summary["updated_missing_unconfirmed_to_canceled"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_marks_old_missing_submitted_canceled_on_first_detection():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        now = datetime.now(timezone.utc)
        order = TradeOrder(
            run_id=None,
            client_order_id="1:AAPL:BUY:2",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={"event_tag": "oi_1_2"},
        )
        session.add(order)
        session.commit()

        # Simulate an old submitted order that has been unchanged for a long time.
        order.updated_at = (now - timedelta(seconds=360)).replace(tzinfo=None)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_3", "symbol": "MSFT"}],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper", now=now)

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "CANCELED"
        params = dict(refreshed.params or {})
        assert params.get("sync_reason") == "missing_from_open_orders"
        assert params.get("open_orders_missing_unconfirmed") is True
        assert summary["updated"] == 1
        assert summary["updated_missing_to_canceled"] == 1
        assert summary["updated_missing_unconfirmed_to_canceled"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_run_scoped_missing_submitted_uses_longer_grace():
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
            status="SUBMITTED",
            params={
                "event_tag": "oi_1_1",
                "open_orders_missing_since": (now - timedelta(seconds=120)).isoformat().replace("+00:00", "Z"),
            },
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_2", "symbol": "MSFT"}],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper", now=now)

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "SUBMITTED"
        assert summary["updated"] == 0
        assert summary["skipped_missing_grace"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_run_scoped_missing_submitted_finalizes_faster_when_executor_inactive():
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
            status="SUBMITTED",
            params={
                "event_tag": "oi_1_1",
                "open_orders_missing_since": (now - timedelta(seconds=120)).isoformat().replace("+00:00", "Z"),
            },
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_2", "symbol": "MSFT"}],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(
            session,
            open_orders,
            mode="paper",
            run_id=run.id,
            now=now,
            run_executor_active=False,
        )

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "CANCELED"
        params = dict(refreshed.params or {})
        assert params.get("sync_reason") == "missing_from_open_orders"
        assert params.get("open_orders_missing_unconfirmed") is True
        assert summary["updated"] == 1
        assert summary["updated_missing_to_canceled"] == 1
        assert summary["updated_missing_unconfirmed_to_canceled"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_keeps_missing_submitted_within_active_grace():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        now = datetime.now(timezone.utc)
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
            params={
                "event_tag": "oi_1_1",
                "open_orders_missing_since": (now - timedelta(seconds=20)).isoformat().replace("+00:00", "Z"),
            },
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_2", "symbol": "MSFT"}],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper", now=now)

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "SUBMITTED"
        assert summary["updated"] == 0
        assert summary["skipped_missing_grace"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_marks_cancel_requested_missing_as_canceled():
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
            status="CANCEL_REQUESTED",
            params={"event_tag": "oi_1_1"},
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_2", "symbol": "MSFT"}],
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


def test_sync_trade_orders_from_open_orders_skips_when_snapshot_empty():
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
        assert refreshed.status == "SUBMITTED"
        assert summary["updated"] == 0
        assert summary["skipped_empty_snapshot"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_allows_run_scoped_empty_to_cancel_requested():
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
            status="CANCEL_REQUESTED",
            params={"event_tag": "oi_1_1"},
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [],
            "refreshed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "source_detail": "ib_open_orders_empty",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper", run_id=run.id)

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "CANCELED"
        assert summary["updated"] == 1
        assert summary["skipped_empty_snapshot"] == 0
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


def test_sync_trade_orders_from_open_orders_clears_missing_unconfirmed_flags_when_tag_returns():
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
            params={
                "event_tag": "oi_1_1",
                "open_orders_missing_since": "2026-02-12T00:00:00Z",
                "open_orders_missing_last_seen": "2026-02-12T00:00:20Z",
                "open_orders_missing_unconfirmed": True,
            },
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
        params = dict(refreshed.params or {})
        assert "open_orders_missing_since" not in params
        assert "open_orders_missing_last_seen" not in params
        assert "open_orders_missing_unconfirmed" not in params
        assert summary["updated"] == 0
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_does_not_force_cancel_for_submitted():
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
            "items": [{"tag": "oi_1_1", "symbol": "AAPL", "status": "Canceled"}],
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


def test_sync_trade_orders_from_open_orders_confirms_manual_submitted_when_open_status_canceled():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        order = TradeOrder(
            run_id=None,
            client_order_id="direct:1",
            symbol="AAPL",
            side="SELL",
            quantity=1,
            order_type="MKT",
            limit_price=None,
            status="SUBMITTED",
            params={"event_tag": "direct:1", "mode": "paper", "source": "manual"},
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "direct:1", "symbol": "AAPL", "status": "Canceled"}],
            "refreshed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "source_detail": "ib_open_orders",
            "bridge_client_id": 0,
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper")

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "CANCELED"
        params = dict(refreshed.params or {})
        assert params.get("sync_reason") == "open_order_reports_canceled"
        assert summary["updated"] == 1
        assert summary["updated_missing_to_canceled"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_uses_client_order_id_when_event_tag_mismatched():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        order = TradeOrder(
            run_id=None,
            client_order_id="oi_manual_abc_1",
            symbol="AAPL",
            side="SELL",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={
                # Historical inconsistent state: event tag does not match broker order tag.
                "event_tag": "direct:3192",
                "mode": "paper",
                "source": "manual",
            },
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_manual_abc_1", "symbol": "AAPL", "status": "Submitted"}],
            "refreshed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "source_detail": "ib_open_orders",
            "bridge_client_id": 0,
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper")

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "SUBMITTED"
        params = dict(refreshed.params or {})
        assert params.get("open_orders_missing_since") is None
        assert summary["updated"] == 0
        assert summary["skipped_missing_grace"] == 0
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_confirms_cancel_requested_when_open_status_canceled():
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
            status="CANCEL_REQUESTED",
            params={"event_tag": "oi_1_1"},
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_1", "symbol": "AAPL", "status": "Canceled"}],
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
            status="CANCEL_REQUESTED",
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
            "items": [{"tag": "oi_2_1", "symbol": "MSFT"}],
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


def test_sync_trade_orders_from_open_orders_skips_when_client_scoped_and_no_overlap():
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
            status="SUBMITTED",
            params={"event_tag": "oi_1_1"},
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_999_1", "symbol": "MSFT"}],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "source_detail": "ib_open_orders",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper", run_id=run.id)

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "SUBMITTED"
        assert summary["updated"] == 0
        assert summary["skipped_no_overlap"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_does_not_cancel_missing_when_client_scoped_global():
    """IB GetOpenOrders is client-id scoped; global reconcile must not infer missing => canceled."""
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        now = datetime.now(timezone.utc)
        run1 = TradeRun(project_id=1, decision_snapshot_id=1, status="running", mode="paper", params={})
        run2 = TradeRun(project_id=1, decision_snapshot_id=1, status="running", mode="paper", params={})
        session.add_all([run1, run2])
        session.commit()

        order1 = TradeOrder(
            run_id=run1.id,
            client_order_id="oi_1_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={"event_tag": "oi_1_1"},
        )
        order2 = TradeOrder(
            run_id=run2.id,
            client_order_id="oi_2_1",
            symbol="MSFT",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={"event_tag": "oi_2_1"},
        )
        session.add_all([order1, order2])
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_1", "symbol": "AAPL"}],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "source_detail": "ib_open_orders",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper", run_id=None)

        assert session.get(TradeOrder, order1.id).status == "SUBMITTED"
        assert session.get(TradeOrder, order2.id).status == "SUBMITTED"
        assert summary["updated"] == 0
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_can_infer_missing_when_client_scoped_master_global():
    """When leader is IB master client (id=0), client-scoped snapshots can be treated as global."""
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        now = datetime.now(timezone.utc)
        order = TradeOrder(
            run_id=None,
            client_order_id="direct:1",
            symbol="AAPL",
            side="SELL",
            quantity=1,
            order_type="MKT",
            limit_price=None,
            status="SUBMITTED",
            params={"event_tag": "direct:1", "mode": "paper"},
        )
        session.add(order)
        session.commit()

        order.updated_at = (now - timedelta(seconds=360)).replace(tzinfo=None)
        session.commit()

        open_orders = {
            "items": [{"tag": "direct:2", "symbol": "MSFT"}],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "source_detail": "ib_open_orders",
            "bridge_client_id": 0,
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper", run_id=None, now=now)

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "CANCELED"
        assert summary["updated"] == 1
        assert summary["updated_missing_to_canceled"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_can_infer_missing_when_client_scoped_master_global_empty():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        now = datetime.now(timezone.utc)
        order = TradeOrder(
            run_id=None,
            client_order_id="direct:1",
            symbol="AAPL",
            side="SELL",
            quantity=1,
            order_type="MKT",
            limit_price=None,
            status="SUBMITTED",
            params={"event_tag": "direct:1", "mode": "paper"},
        )
        session.add(order)
        session.commit()

        order.updated_at = (now - timedelta(seconds=360)).replace(tzinfo=None)
        session.commit()

        open_orders = {
            "items": [],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "source_detail": "ib_open_orders_empty",
            "bridge_client_id": 0,
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper", run_id=None, now=now)

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "CANCELED"
        assert summary["updated"] == 1
        assert summary["updated_missing_to_canceled"] == 1
        assert summary["skipped_empty_snapshot"] == 0
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_manual_missing_submitted_finalizes_faster():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        now = datetime.now(timezone.utc)
        order = TradeOrder(
            run_id=None,
            client_order_id="oi_999_manual",
            symbol="AAPL",
            side="SELL",
            quantity=1,
            order_type="MKT",
            limit_price=None,
            status="SUBMITTED",
            params={"event_tag": "direct:999", "mode": "paper", "source": "manual"},
        )
        session.add(order)
        session.commit()

        order.updated_at = (now - timedelta(seconds=120)).replace(tzinfo=None)
        session.commit()

        open_orders = {
            "items": [],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "source_detail": "ib_open_orders_empty",
            "bridge_client_id": 0,
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper", run_id=None, now=now)

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "CANCELED"
        assert summary["updated"] == 1
        assert summary["updated_missing_to_canceled"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_manual_missing_submitted_cancels_after_shorter_unconfirmed_window():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        now = datetime.now(timezone.utc)
        order = TradeOrder(
            run_id=None,
            client_order_id="oi_1000_manual",
            symbol="AAPL",
            side="SELL",
            quantity=1,
            order_type="MKT",
            limit_price=None,
            status="SUBMITTED",
            params={
                "event_tag": "direct:1000",
                "mode": "paper",
                "source": "manual",
                "open_orders_missing_since": (now - timedelta(seconds=50)).isoformat().replace("+00:00", "Z"),
            },
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "source_detail": "ib_open_orders_empty",
            "bridge_client_id": 0,
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(session, open_orders, mode="paper", run_id=None, now=now)

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "CANCELED"
        params = dict(refreshed.params or {})
        assert params.get("sync_reason") == "missing_from_open_orders"
        assert summary["updated"] == 1
        assert summary["updated_missing_unconfirmed_to_canceled"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_run_scoped_missing_new_promotes_to_submitted():
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
            "items": [{"tag": "oi_1_2", "symbol": "MSFT"}],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(
            session, open_orders, mode="paper", run_id=run.id, include_new=True, now=now
        )

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "SUBMITTED"
        params = dict(refreshed.params or {})
        assert params.get("sync_reason") == "missing_from_open_orders"
        assert params.get("open_orders_missing_since")
        assert params.get("open_orders_missing_last_seen")
        assert params.get("open_orders_missing_unconfirmed") is True
        assert summary["updated"] == 1
        assert summary["updated_new_to_submitted"] == 1
        assert summary["updated_missing_to_skipped"] == 0
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_does_not_skip_pending_submit_new_order():
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
            params={
                "event_tag": "oi_1_1",
                "submit_command": {
                    "pending": True,
                    "command_id": "submit_order_1_x",
                    "requested_at": (now - timedelta(seconds=90)).isoformat().replace("+00:00", "Z"),
                },
            },
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_2", "symbol": "MSFT"}],
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
        assert summary["skipped_submit_pending"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_does_not_skip_short_lived_fallback_new_order_within_grace():
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
            created_at=now - timedelta(seconds=180),
            params={
                "event_tag": "oi_1_1",
                "submit_command": {
                    "pending": False,
                    "status": "superseded",
                    "source": "leader_command",
                    "reason": "leader_submit_pending_timeout",
                    "superseded_by": "short_lived_fallback",
                    "processed_at": (now - timedelta(seconds=20)).isoformat().replace("+00:00", "Z"),
                    "expires_at": (now + timedelta(seconds=40)).isoformat().replace("+00:00", "Z"),
                },
            },
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_2", "symbol": "MSFT"}],
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
        assert summary["skipped_submit_pending"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_can_skip_short_lived_fallback_new_order_after_grace():
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
            created_at=now - timedelta(seconds=900),
            params={
                "event_tag": "oi_1_1",
                "submit_command": {
                    "pending": False,
                    "status": "superseded",
                    "source": "leader_command",
                    "reason": "leader_submit_pending_timeout",
                    "superseded_by": "short_lived_fallback",
                    "processed_at": (now - timedelta(seconds=600)).isoformat().replace("+00:00", "Z"),
                    "expires_at": (now - timedelta(seconds=120)).isoformat().replace("+00:00", "Z"),
                },
            },
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_2", "symbol": "MSFT"}],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(
            session, open_orders, mode="paper", run_id=run.id, include_new=True, now=now
        )

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "SKIPPED"
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
            "items": [{"tag": "oi_1_2", "symbol": "MSFT"}],
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
            params={
                "event_tag": "oi_1_1",
                "sync_reason": "missing_from_open_orders",
                "event_source": "lean_open_orders",
                "event_status": "CANCELED",
            },
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
        params = dict(refreshed.params or {})
        assert params.get("sync_reason") == "present_in_open_orders_recovered"
        assert params.get("event_source") == "lean_open_orders"
        assert summary["updated"] == 1
    finally:
        session.close()


def test_sync_trade_orders_from_open_orders_does_not_recover_execution_canceled_when_tag_present():
    from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders

    session = _make_session()
    try:
        now = datetime.now(timezone.utc)
        run = TradeRun(project_id=1, decision_snapshot_id=1, status="running", mode="paper", params={})
        session.add(run)
        session.commit()

        order = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1_2",
            symbol="MSFT",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="CANCELED",
            created_at=now - timedelta(seconds=120),
            params={
                "event_tag": "oi_1_2",
                "event_source": "lean",
                "event_status": "CANCELED",
            },
        )
        session.add(order)
        session.commit()

        open_orders = {
            "items": [{"tag": "oi_1_2", "symbol": "MSFT", "status": "Submitted"}],
            "refreshed_at": now.isoformat().replace("+00:00", "Z"),
            "source": "lean_bridge",
            "stale": False,
        }
        summary = sync_trade_orders_from_open_orders(
            session, open_orders, mode="paper", run_id=run.id, include_new=True, now=now
        )

        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "CANCELED"
        params = dict(refreshed.params or {})
        assert params.get("event_source") == "lean"
        assert params.get("event_status") == "CANCELED"
        assert summary["updated"] == 0
    finally:
        session.close()
