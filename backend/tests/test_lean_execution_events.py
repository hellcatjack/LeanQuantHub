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

from app.models import Base, TradeOrder, TradeRun
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
