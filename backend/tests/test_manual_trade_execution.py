from pathlib import Path
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base
from app.services.trade_orders import create_trade_order
from app.services import manual_trade_execution
from app.services.manual_trade_execution import write_manual_order_intent


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_write_manual_order_intent_builds_quantity(tmp_path):
    session = _make_session()
    try:
        payload = {
            "client_order_id": "oi_0_0_123",
            "symbol": "AAPL",
            "side": "SELL",
            "quantity": 1,
            "order_type": "MKT",
        }
        order = create_trade_order(session, payload).order
        session.commit()

        path = write_manual_order_intent(order, output_dir=tmp_path)
        text = Path(path).read_text(encoding="utf-8")
        assert "order_intent_id" in text
        assert "oi_0_0_123" in text
        assert "\"quantity\": -1" in text
    finally:
        session.close()


def test_execute_manual_order_launches(monkeypatch, tmp_path):
    session = _make_session()
    try:
        payload = {
            "client_order_id": "oi_0_0_456",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
        }
        order = create_trade_order(session, payload).order
        session.commit()

        calls = {"config_path": None}

        def _fake_launch(config_path: str) -> None:
            calls["config_path"] = config_path

        monkeypatch.setattr(manual_trade_execution, "launch_execution", _fake_launch, raising=False)
        monkeypatch.setattr(manual_trade_execution, "ARTIFACT_ROOT", tmp_path, raising=False)

        manual_trade_execution.execute_manual_order(
            session,
            order,
            project_id=16,
            mode="paper",
        )

        assert calls["config_path"] is not None
        assert order.params["manual_execution"]["project_id"] == 16
        assert order.params["manual_execution"]["mode"] == "paper"
    finally:
        session.close()
