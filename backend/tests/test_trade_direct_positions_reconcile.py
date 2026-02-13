from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models import Base, TradeFill, TradeOrder


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_reconcile_direct_orders_with_positions_infers_fill_from_executor_baseline(tmp_path, monkeypatch):
    from app.services.trade_executor import reconcile_direct_orders_with_positions

    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    bridge_root = tmp_path / "lean_bridge"

    session = _make_session()
    try:
        order = TradeOrder(
            run_id=None,
            client_order_id="direct:1",
            symbol="AMSC",
            side="SELL",
            quantity=1.0,
            order_type="MKT",
            limit_price=None,
            status="CANCEL_REQUESTED",
            filled_quantity=0.0,
            avg_fill_price=None,
            params={"mode": "paper", "event_tag": "direct:1"},
            created_at=datetime.utcnow() - timedelta(minutes=10),
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        # Baseline captured by direct executor at submission time: quantity was 40.
        direct_dir = bridge_root / f"direct_{order.id}"
        direct_dir.mkdir(parents=True, exist_ok=True)
        (direct_dir / "positions.json").write_text(
            json.dumps(
                {
                    "items": [{"symbol": "AMSC", "quantity": 40.0, "avg_cost": 29.0}],
                    "refreshed_at": "2026-02-10T14:05:00Z",
                    "stale": False,
                }
            ),
            encoding="utf-8",
        )

        # Current holdings show quantity decreased to 39, implying the SELL filled by 1.
        positions_payload = {
            "items": [{"symbol": "AMSC", "quantity": 39.0, "avg_cost": 29.5}],
            "refreshed_at": "2026-02-10T14:40:00Z",
            "stale": False,
        }

        out = reconcile_direct_orders_with_positions(session, positions_payload, now=datetime.utcnow())
        assert out["reconciled"] == 1

        session.refresh(order)
        assert order.status == "FILLED"
        assert float(order.filled_quantity or 0.0) == 1.0
        assert float(order.avg_fill_price or 0.0) > 0

        fills = session.query(TradeFill).filter(TradeFill.order_id == order.id).all()
        assert len(fills) == 1
        assert fills[0].fill_quantity == 1.0
        assert fills[0].fill_price > 0

        # Idempotent: running again shouldn't create a second fill.
        out2 = reconcile_direct_orders_with_positions(session, positions_payload, now=datetime.utcnow())
        assert out2["reconciled"] == 0
        fills2 = session.query(TradeFill).filter(TradeFill.order_id == order.id).all()
        assert len(fills2) == 1
    finally:
        session.close()


def test_reconcile_direct_orders_with_positions_handles_empty_holdings_snapshot(tmp_path, monkeypatch):
    from app.services.trade_executor import reconcile_direct_orders_with_positions

    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    bridge_root = tmp_path / "lean_bridge"

    session = _make_session()
    try:
        order = TradeOrder(
            run_id=None,
            client_order_id="direct:2",
            symbol="AMSC",
            side="SELL",
            quantity=2.0,
            order_type="ADAPTIVE_LMT",
            limit_price=None,
            status="SUBMITTED",
            filled_quantity=0.0,
            avg_fill_price=None,
            params={"mode": "paper", "event_tag": "direct:2"},
            created_at=datetime.utcnow() - timedelta(minutes=10),
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        direct_dir = bridge_root / f"direct_{order.id}"
        direct_dir.mkdir(parents=True, exist_ok=True)
        (direct_dir / "positions.json").write_text(
            json.dumps(
                {
                    "items": [{"symbol": "AMSC", "quantity": 2.0, "avg_cost": 33.5}],
                    "refreshed_at": "2026-02-11T20:35:00Z",
                    "stale": False,
                }
            ),
            encoding="utf-8",
        )

        # Holdings snapshot is empty (all positions already closed).
        positions_payload = {
            "items": [],
            "refreshed_at": "2026-02-11T20:40:00Z",
            "stale": False,
        }

        out = reconcile_direct_orders_with_positions(session, positions_payload, now=datetime.utcnow())
        assert out["reconciled"] == 1

        session.refresh(order)
        assert order.status == "FILLED"
        assert float(order.filled_quantity or 0.0) == 2.0
        assert float(order.avg_fill_price or 0.0) == 33.5

        fills = session.query(TradeFill).filter(TradeFill.order_id == order.id).all()
        assert len(fills) == 1
        assert fills[0].fill_quantity == 2.0
    finally:
        session.close()


def test_reconcile_direct_orders_with_positions_terminalizes_superseded_submitted_without_fill(tmp_path, monkeypatch):
    from app.services.trade_executor import reconcile_direct_orders_with_positions

    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    bridge_root = tmp_path / "lean_bridge"

    session = _make_session()
    try:
        order = TradeOrder(
            run_id=None,
            client_order_id="direct:3",
            symbol="AMSC",
            side="SELL",
            quantity=2.0,
            order_type="ADAPTIVE_LMT",
            limit_price=None,
            status="SUBMITTED",
            filled_quantity=0.0,
            avg_fill_price=None,
            params={
                "mode": "paper",
                "event_tag": "direct:3",
                "submit_command": {
                    "pending": False,
                    "status": "superseded",
                    "source": "leader_command",
                    "reason": "leader_submit_pending_timeout",
                },
            },
            created_at=datetime.utcnow() - timedelta(minutes=20),
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        direct_dir = bridge_root / f"direct_{order.id}"
        direct_dir.mkdir(parents=True, exist_ok=True)
        (direct_dir / "positions.json").write_text(
            json.dumps(
                {
                    "items": [{"symbol": "AMSC", "quantity": 2.0, "avg_cost": 33.5}],
                    "refreshed_at": "2026-02-11T20:35:00Z",
                    "stale": False,
                }
            ),
            encoding="utf-8",
        )

        # No position delta means this order has no observed fill.
        positions_payload = {
            "items": [{"symbol": "AMSC", "quantity": 2.0, "avg_cost": 33.5}],
            "refreshed_at": "2026-02-11T20:40:00Z",
            "stale": False,
        }

        out = reconcile_direct_orders_with_positions(session, positions_payload, now=datetime.utcnow())
        assert out["terminalized_no_fill_timeout"] == 1

        session.refresh(order)
        assert order.status == "CANCELED"
        params = dict(order.params or {})
        assert params.get("sync_reason") == "leader_submit_no_fill_timeout"
    finally:
        session.close()
