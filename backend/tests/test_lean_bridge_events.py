from pathlib import Path
import sys
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeOrder
from app.services import lean_bridge


def test_ingest_execution_events_updates_order(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(lean_bridge, "SessionLocal", Session, raising=False)

    session = Session()
    order = TradeOrder(
        run_id=1,
        client_order_id="run1:AAPL:BUY",
        symbol="AAPL",
        side="BUY",
        quantity=1,
        status="NEW",
    )
    session.add(order)
    session.commit()
    order_id = order.id
    session.close()

    events_path = tmp_path / "execution_events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "order_id": order_id,
                "status": "FILLED",
                "avg_price": 100,
                "filled": 1,
                "exec_id": "e1",
            }
        )
        + "\n"
    )
    monkeypatch.setattr(lean_bridge, "BRIDGE_ROOT", tmp_path, raising=False)

    lean_bridge.ingest_execution_events()

    session = Session()
    refreshed = session.get(TradeOrder, order_id)
    assert refreshed.status == "FILLED"
    session.close()
