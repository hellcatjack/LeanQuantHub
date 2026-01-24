from pathlib import Path
import json
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, DecisionSnapshot
from app.services import trade_order_intent


def test_build_order_intent_writes_min_fields(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        snapshot = DecisionSnapshot(
            project_id=1,
            status="success",
            snapshot_date="2026-01-16",
            items_path=str(tmp_path / "items.csv"),
        )
        session.add(snapshot)
        session.commit()
        items = [
            {
                "symbol": "AAPL",
                "weight": 0.1,
                "snapshot_date": "2026-01-16",
                "rebalance_date": "2026-01-16",
            },
        ]
        output = trade_order_intent.write_order_intent(
            session,
            snapshot_id=snapshot.id,
            items=items,
            output_dir=tmp_path,
        )
        payload = json.loads(Path(output).read_text())
        assert payload[0]["symbol"] == "AAPL"
        assert "weight" in payload[0]
        assert "snapshot_date" in payload[0]
    finally:
        session.close()
