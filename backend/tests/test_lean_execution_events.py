from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeFill, TradeOrder, TradeRun
from app.services.lean_execution import apply_execution_events


def _write_intent_file(path: Path, run_id: int) -> None:
    payload = [
        {
            "order_intent_id": f"oi_{run_id}_1",
            "symbol": "AMAT",
            "weight": 0.1,
            "snapshot_date": "2026-01-23",
            "rebalance_date": "2026-01-23",
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_apply_execution_events_creates_and_fills_missing_order(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        run = TradeRun(project_id=1, decision_snapshot_id=25, status="running", params={})
        session.add(run)
        session.commit()
        intent_path = tmp_path / "order_intent.json"
        _write_intent_file(intent_path, run.id)
        run.params = {"order_intent_path": str(intent_path)}
        session.commit()

        events = [
            {
                "order_id": 9,
                "symbol": "AMAT",
                "status": "Filled",
                "filled": 3.0,
                "fill_price": 334.15,
                "exec_id": "exec-missing-oi-1",
                "direction": "Buy",
                "time": "2026-01-27T15:25:46.9105632Z",
                "tag": f"oi_{run.id}_1",
            }
        ]

        apply_execution_events(events, session=session)

        order = session.query(TradeOrder).filter(TradeOrder.client_order_id == f"oi_{run.id}_1").one()
        assert order.status == "FILLED"
        assert float(order.filled_quantity) == 3.0
        assert float(order.avg_fill_price) == 334.15
        assert order.ib_order_id == 9
        assert isinstance(order.params, dict)
        assert order.params.get("event_status") == "FILLED"
        assert order.params.get("sync_reason") == "execution_fill"
    finally:
        session.close()


def test_apply_execution_events_rejects_invalid_tag(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        events = [
            {
                "order_id": 1,
                "symbol": "AMD",
                "status": "Filled",
                "filled": 1.0,
                "fill_price": 10.0,
                "direction": "Buy",
                "time": "2026-01-27T00:00:00Z",
                "tag": "not-json",
            }
        ]

        result = apply_execution_events(events, session=session)

        assert result["skipped_invalid_tag"] == 1
        order = session.query(TradeOrder).filter(TradeOrder.ib_order_id == 1).first()
        assert order is None
    finally:
        session.close()


def test_apply_execution_events_reuses_existing_order(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        run = TradeRun(project_id=1, decision_snapshot_id=63, status="running", params={})
        session.add(run)
        session.commit()
        intent_path = tmp_path / "order_intent.json"
        intent_payload = [
            {
                "order_intent_id": f"oi_{run.id}_1",
                "symbol": "AAPL",
                "quantity": 1,
                "weight": 0,
            }
        ]
        intent_path.write_text(json.dumps(intent_payload), encoding="utf-8")
        run.params = {"order_intent_path": str(intent_path)}
        session.commit()

        existing = TradeOrder(
            run_id=run.id,
            client_order_id=f"{run.id}:AAPL:BUY:{run.decision_snapshot_id}",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="MKT",
        )
        session.add(existing)
        session.commit()

        events = [
            {
                "order_id": 10,
                "symbol": "AAPL",
                "status": "Filled",
                "filled": 1.0,
                "fill_price": 100.0,
                "exec_id": "exec-reuse-oi-1",
                "direction": "Buy",
                "time": "2026-01-27T15:25:46.9105632Z",
                "tag": f"oi_{run.id}_1",
            }
        ]

        apply_execution_events(events, session=session)

        assert session.query(TradeOrder).count() == 1
        refreshed = session.query(TradeOrder).filter_by(id=existing.id).one()
        assert refreshed.status == "FILLED"
        assert float(refreshed.filled_quantity) == 1.0
        assert float(refreshed.avg_fill_price) == 100.0
    finally:
        session.close()


def test_apply_execution_events_submitted_matches_existing_order_without_intent_quantity(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        run = TradeRun(project_id=1, decision_snapshot_id=25, status="running", params={})
        session.add(run)
        session.commit()
        intent_path = tmp_path / "order_intent.json"
        _write_intent_file(intent_path, run.id)
        run.params = {"order_intent_path": str(intent_path)}
        session.commit()

        existing = TradeOrder(
            run_id=run.id,
            client_order_id=f"{run.id}:AMAT:BUY:{run.decision_snapshot_id}",
            symbol="AMAT",
            side="BUY",
            quantity=3,
            order_type="MKT",
            status="NEW",
        )
        session.add(existing)
        session.commit()

        events = [
            {
                "order_id": 101,
                "symbol": "AMAT",
                "status": "Submitted",
                "filled": 0.0,
                "fill_price": 0.0,
                "direction": "Buy",
                "time": "2026-01-27T15:25:46.9105632Z",
                "tag": f"oi_{run.id}_1",
            }
        ]

        apply_execution_events(events, session=session)

        assert session.query(TradeOrder).count() == 1
        refreshed = session.query(TradeOrder).filter_by(id=existing.id).one()
        assert refreshed.status == "SUBMITTED"
        assert refreshed.ib_order_id == 101
    finally:
        session.close()


def test_apply_execution_events_merges_mismatched_run(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        run = TradeRun(project_id=1, decision_snapshot_id=63, status="running", params={})
        other_run = TradeRun(project_id=1, decision_snapshot_id=63, status="running", params={})
        session.add_all([run, other_run])
        session.commit()

        intent_path = tmp_path / "order_intent.json"
        intent_payload = [
            {
                "order_intent_id": f"oi_{run.id}_1",
                "symbol": "AAPL",
                "quantity": 1,
                "weight": 0,
            }
        ]
        intent_path.write_text(json.dumps(intent_payload), encoding="utf-8")
        run.params = {"order_intent_path": str(intent_path)}
        session.commit()

        canonical = TradeOrder(
            run_id=run.id,
            client_order_id=f"{run.id}:AAPL:BUY:{run.decision_snapshot_id}",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="MKT",
        )
        duplicate = TradeOrder(
            run_id=other_run.id,
            client_order_id=f"oi_{run.id}_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="MKT",
            status="FILLED",
            filled_quantity=1,
            avg_fill_price=100.0,
            ib_order_id=99,
        )
        session.add_all([canonical, duplicate])
        session.commit()

        fill = TradeFill(
            order_id=duplicate.id,
            exec_id="lean:dup",
            fill_quantity=1,
            fill_price=100.0,
        )
        session.add(fill)
        session.commit()

        events = [
            {
                "order_id": 99,
                "symbol": "AAPL",
                "status": "Filled",
                "filled": 1.0,
                "fill_price": 100.0,
                "exec_id": "exec-merge-oi-1",
                "direction": "Buy",
                "time": "2026-01-27T15:25:46.9105632Z",
                "tag": f"oi_{run.id}_1",
            }
        ]

        apply_execution_events(events, session=session)

        assert session.query(TradeOrder).filter_by(id=duplicate.id).first() is None
        refreshed = session.query(TradeOrder).filter_by(id=canonical.id).one()
        assert refreshed.status == "FILLED"
        assert refreshed.filled_quantity == 1
        assert refreshed.avg_fill_price == 100.0
        assert refreshed.ib_order_id == 99
        moved_fill = session.query(TradeFill).filter_by(exec_id="lean:dup").one()
        assert moved_fill.order_id == canonical.id
    finally:
        session.close()


def test_apply_execution_events_dedups_synthetic_and_ib_exec_ids():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        order = TradeOrder(
            client_order_id="direct-dedup-1",
            symbol="AXON",
            side="BUY",
            quantity=1,
            order_type="ADAPTIVE_LMT",
            status="FILLED",
            filled_quantity=1,
            avg_fill_price=435.03,
            ib_order_id=1459,
        )
        session.add(order)
        session.commit()

        session.add(
            TradeFill(
                order_id=order.id,
                exec_id=f"lean_direct:{order.id}:1770827978884",
                fill_quantity=1,
                fill_price=435.03,
                fill_time=datetime(2026, 2, 11, 16, 39, 39),
            )
        )
        session.commit()

        events = [
            {
                "order_id": 1459,
                "symbol": "AXON",
                "status": "Filled",
                "filled": 1.0,
                "fill_price": 435.03,
                "direction": "Buy",
                "time": "2026-02-11T16:39:38Z",
                "tag": f"direct:{order.id}",
                "exec_id": "0000dc8f.69c6551b.01.01",
            }
        ]

        apply_execution_events(events, session=session)

        refreshed = session.query(TradeOrder).filter_by(id=order.id).one()
        assert refreshed.status == "FILLED"
        assert float(refreshed.filled_quantity) == 1.0
        fills = session.query(TradeFill).filter_by(order_id=order.id).all()
        assert len(fills) == 1
    finally:
        session.close()


def test_apply_execution_events_maps_cancel_pending_to_cancel_requested_for_direct_order():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        order = TradeOrder(
            client_order_id="direct-cancel-pending-1",
            symbol="AXON",
            side="BUY",
            quantity=1,
            order_type="ADAPTIVE_LMT",
            status="SUBMITTED",
            ib_order_id=2016,
        )
        session.add(order)
        session.commit()

        events = [
            {
                "order_id": 2016,
                "symbol": "AXON",
                "status": "CancelPending",
                "filled": 0.0,
                "fill_price": 0.0,
                "direction": "Buy",
                "time": "2026-02-11T16:55:01Z",
                "tag": f"direct:{order.id}",
            }
        ]

        apply_execution_events(events, session=session)

        refreshed = session.query(TradeOrder).filter_by(id=order.id).one()
        assert refreshed.status == "CANCEL_REQUESTED"
        params = refreshed.params or {}
        assert params.get("sync_reason") == "execution_cancel_pending"
        assert params.get("event_status") == "CANCEL_REQUESTED"
    finally:
        session.close()


def test_apply_execution_events_marks_oi_order_canceled(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        run = TradeRun(project_id=1, decision_snapshot_id=25, status="running", params={})
        session.add(run)
        session.commit()

        intent_path = tmp_path / "order_intent.json"
        intent_payload = [
            {
                "order_intent_id": f"oi_{run.id}_1",
                "symbol": "AAPL",
                "quantity": 1,
                "weight": 0,
            }
        ]
        intent_path.write_text(json.dumps(intent_payload), encoding="utf-8")
        run.params = {"order_intent_path": str(intent_path)}
        session.commit()

        order = TradeOrder(
            run_id=run.id,
            client_order_id=f"oi_{run.id}_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
        )
        session.add(order)
        session.commit()

        events = [
            {
                "order_id": 123,
                "symbol": "AAPL",
                "status": "Canceled",
                "filled": 0.0,
                "fill_price": 0.0,
                "direction": "Buy",
                "time": "2026-01-27T15:25:46.9105632Z",
                "tag": f"oi_{run.id}_1",
            }
        ]

        apply_execution_events(events, session=session)

        refreshed = session.query(TradeOrder).filter_by(id=order.id).one()
        assert refreshed.status == "CANCELED"
        assert refreshed.ib_order_id == 123
        assert isinstance(refreshed.params, dict)
        assert refreshed.params.get("event_tag") == f"oi_{run.id}_1"
        assert refreshed.params.get("event_status") == "CANCELED"
    finally:
        session.close()


def test_apply_execution_events_marks_oi_order_rejected(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        run = TradeRun(project_id=1, decision_snapshot_id=25, status="running", params={})
        session.add(run)
        session.commit()

        intent_path = tmp_path / "order_intent.json"
        intent_payload = [
            {
                "order_intent_id": f"oi_{run.id}_1",
                "symbol": "AAPL",
                "quantity": 1,
                "weight": 0,
            }
        ]
        intent_path.write_text(json.dumps(intent_payload), encoding="utf-8")
        run.params = {"order_intent_path": str(intent_path)}
        session.commit()

        order = TradeOrder(
            run_id=run.id,
            client_order_id=f"oi_{run.id}_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="MKT",
            status="NEW",
        )
        session.add(order)
        session.commit()

        events = [
            {
                "order_id": 77,
                "symbol": "AAPL",
                "status": "Rejected",
                "filled": 0.0,
                "fill_price": 0.0,
                "direction": "Buy",
                "time": "2026-01-27T15:25:46.9105632Z",
                "tag": f"oi_{run.id}_1",
                "reason": "Order rejected by exchange",
            }
        ]

        apply_execution_events(events, session=session)

        refreshed = session.query(TradeOrder).filter_by(id=order.id).one()
        assert refreshed.status == "REJECTED"
        assert refreshed.ib_order_id == 77
        assert isinstance(refreshed.params, dict)
        assert refreshed.params.get("event_status") == "REJECTED"
        assert "reason" in (refreshed.params or {})
    finally:
        session.close()


def test_apply_execution_events_recovers_oi_order_skipped_to_rejected(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        run = TradeRun(project_id=1, decision_snapshot_id=25, status="running", params={})
        session.add(run)
        session.commit()

        order = TradeOrder(
            run_id=run.id,
            client_order_id=f"oi_{run.id}_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="MKT",
            status="SKIPPED",
            params={
                "event_source": "lean_open_orders",
                "sync_reason": "missing_from_open_orders",
                "event_tag": f"oi_{run.id}_1",
            },
        )
        session.add(order)
        session.commit()

        events = [
            {
                "order_id": 77,
                "symbol": "AAPL",
                "status": "Invalid",
                "filled": 0.0,
                "fill_price": 0.0,
                "direction": "Buy",
                "time": "2026-01-27T15:25:46.9105632Z",
                "tag": f"oi_{run.id}_1",
                "reason": "PlaceOrderWhenDisconnected",
            }
        ]

        apply_execution_events(events, session=session)

        refreshed = session.query(TradeOrder).filter_by(id=order.id).one()
        assert refreshed.status == "REJECTED"
        assert refreshed.ib_order_id == 77
        assert isinstance(refreshed.params, dict)
        assert refreshed.params.get("event_status") == "INVALID"
        assert refreshed.params.get("sync_reason") == "execution_event_rejected_recovered"
        assert refreshed.rejected_reason == "PlaceOrderWhenDisconnected"
    finally:
        session.close()


def test_apply_execution_events_recovers_direct_order_skipped_to_rejected():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        order = TradeOrder(
            client_order_id="direct:test-1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="MKT",
            status="SKIPPED",
            params={
                "event_source": "lean_open_orders",
                "sync_reason": "missing_from_open_orders",
                "event_tag": "direct:1",
            },
        )
        session.add(order)
        session.commit()

        events = [
            {
                "order_id": 107,
                "symbol": "AAPL",
                "status": "Invalid",
                "filled": 0.0,
                "fill_price": 0.0,
                "direction": "Buy",
                "time": "2026-01-27T15:25:46.9105632Z",
                "tag": f"direct:{order.id}",
                "reason": "PlaceOrderWhenDisconnected",
            }
        ]

        apply_execution_events(events, session=session)

        refreshed = session.query(TradeOrder).filter_by(id=order.id).one()
        assert refreshed.status == "REJECTED"
        assert refreshed.ib_order_id == 107
        assert isinstance(refreshed.params, dict)
        assert refreshed.params.get("event_status") == "INVALID"
        assert refreshed.params.get("sync_reason") == "execution_event_rejected_recovered"
        assert refreshed.rejected_reason == "PlaceOrderWhenDisconnected"
    finally:
        session.close()


def test_apply_execution_events_marks_oi_order_partial_fill(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        run = TradeRun(project_id=1, decision_snapshot_id=25, status="running", params={})
        session.add(run)
        session.commit()

        intent_path = tmp_path / "order_intent.json"
        intent_payload = [
            {
                "order_intent_id": f"oi_{run.id}_1",
                "symbol": "AAPL",
                "quantity": 2,
                "weight": 0,
            }
        ]
        intent_path.write_text(json.dumps(intent_payload), encoding="utf-8")
        run.params = {"order_intent_path": str(intent_path)}
        session.commit()

        order = TradeOrder(
            run_id=run.id,
            client_order_id=f"oi_{run.id}_1",
            symbol="AAPL",
            side="BUY",
            quantity=2,
            order_type="MKT",
            status="SUBMITTED",
        )
        session.add(order)
        session.commit()

        events = [
            {
                "order_id": 88,
                "symbol": "AAPL",
                "status": "PartiallyFilled",
                "filled": 1.0,
                "fill_price": 100.0,
                "exec_id": "exec-partial-oi-1",
                "direction": "Buy",
                "time": "2026-01-27T15:25:46.9105632Z",
                "tag": f"oi_{run.id}_1",
            }
        ]

        apply_execution_events(events, session=session)

        refreshed = session.query(TradeOrder).filter_by(id=order.id).one()
        assert refreshed.status == "PARTIAL"
        assert float(refreshed.filled_quantity) == 1.0
        assert float(refreshed.avg_fill_price) == 100.0
        fills = session.query(TradeFill).filter(TradeFill.order_id == order.id).all()
        assert len(fills) == 1
    finally:
        session.close()


def test_apply_execution_events_marks_oi_sell_order_filled_with_negative_quantity(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        run = TradeRun(project_id=1, decision_snapshot_id=25, status="running", params={})
        session.add(run)
        session.commit()

        intent_path = tmp_path / "order_intent.json"
        intent_payload = [
            {
                "order_intent_id": f"oi_{run.id}_1",
                "symbol": "AMSC",
                "quantity": -2,
                "weight": 0,
            }
        ]
        intent_path.write_text(json.dumps(intent_payload), encoding="utf-8")
        run.params = {"order_intent_path": str(intent_path)}
        session.commit()

        order = TradeOrder(
            run_id=run.id,
            client_order_id=f"oi_{run.id}_1",
            symbol="AMSC",
            side="SELL",
            quantity=2,
            order_type="MKT",
            status="SUBMITTED",
        )
        session.add(order)
        session.commit()

        events = [
            {
                "order_id": 201,
                "symbol": "AMSC",
                "status": "Filled",
                "filled": -2.0,
                "fill_price": 14.5,
                "exec_id": "exec-sell-oi-1",
                "direction": "Sell",
                "time": "2026-02-11T10:27:14.0000000Z",
                "tag": f"oi_{run.id}_1",
            }
        ]

        apply_execution_events(events, session=session)

        refreshed = session.query(TradeOrder).filter_by(id=order.id).one()
        assert refreshed.status == "FILLED"
        assert float(refreshed.filled_quantity) == 2.0
        assert float(refreshed.avg_fill_price) == 14.5
        assert refreshed.ib_order_id == 201
        fills = session.query(TradeFill).filter(TradeFill.order_id == order.id).all()
        assert len(fills) == 1
        assert float(fills[0].fill_quantity) == 2.0
    finally:
        session.close()
