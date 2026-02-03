from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models import Base, TradeOrder
from app.services import trade_direct_order
from app.services.trade_direct_intent import build_direct_intent_items
from app.services.trade_orders import create_trade_order
from app.services.ib_client_id_pool import ClientIdPoolExhausted


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_direct_order_client_id_busy_schedules_retry(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))

    monkeypatch.setattr(trade_direct_order, "_select_worker", lambda *_args, **_kwargs: None)

    def _raise_busy(*_args, **_kwargs):
        raise ClientIdPoolExhausted("client_id_busy")

    monkeypatch.setattr(trade_direct_order, "lease_client_id", _raise_busy)
    monkeypatch.setattr(trade_direct_order, "launch_execution_async", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("launch should not run")))
    monkeypatch.setattr(trade_direct_order, "refresh_bridge", lambda *_args, **_kwargs: {})

    session = _make_session()
    payload = {
        "project_id": 18,
        "mode": "paper",
        "client_order_id": "manual-424",
        "symbol": "APH",
        "side": "SELL",
        "quantity": 1,
        "order_type": "MKT",
        "params": {"source": "manual", "project_id": 18},
    }

    result = trade_direct_order.submit_direct_order(session, payload)

    assert result.execution_status == "retry_pending"

    order = session.query(TradeOrder).first()
    assert order is not None
    retry_meta = (order.params or {}).get("direct_retry")
    assert retry_meta is not None
    assert retry_meta.get("pending") is True
    assert retry_meta.get("count") == 1
    assert retry_meta.get("last_reason") == "client_id_busy"


def test_retry_direct_order_launches(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))

    session = _make_session()
    payload = {
        "client_order_id": "manual-500",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 2,
        "order_type": "MKT",
        "params": {"source": "manual", "project_id": 18},
    }
    result = create_trade_order(session, payload)
    session.commit()
    session.refresh(result.order)
    order = result.order

    intent_items = build_direct_intent_items(
        order_id=order.id,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
    )
    intent_dir = Path(settings.artifact_root) / "order_intents"
    intent_dir.mkdir(parents=True, exist_ok=True)
    intent_path = intent_dir / f"order_intent_direct_{order.id}.json"
    intent_path.write_text(
        __import__("json").dumps(intent_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    monkeypatch.setattr(trade_direct_order, "_select_worker", lambda *_args, **_kwargs: 2009)
    monkeypatch.setattr(trade_direct_order, "lease_client_id", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("lease should not be called")))

    captured = {}

    def _fake_build_execution_config(**kwargs):
        captured["client_id"] = kwargs.get("client_id")
        return {"lean-bridge-output-dir": kwargs.get("lean_bridge_output_dir")}

    monkeypatch.setattr(trade_direct_order, "build_execution_config", _fake_build_execution_config)
    monkeypatch.setattr(trade_direct_order, "launch_execution_async", lambda *_args, **_kwargs: 12345)
    monkeypatch.setattr(trade_direct_order, "refresh_bridge", lambda *_args, **_kwargs: {})

    retry_result = trade_direct_order.retry_direct_order(session, order_id=order.id)

    assert retry_result.execution_status == "submitted_lean"
    assert captured["client_id"] == 2009

    config_path = Path(settings.artifact_root) / "lean_execution" / f"direct_order_{order.id}_config.json"
    probe_path = Path(settings.artifact_root) / "lean_execution" / f"direct_order_{order.id}.json"
    assert config_path.exists()
    assert probe_path.exists()

    session.refresh(order)
    retry_meta = (order.params or {}).get("direct_retry")
    assert retry_meta is not None
    assert retry_meta.get("pending") is False
    assert retry_meta.get("count") == 1
