from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models import Base, TradeFill, TradeOrder
from app.services.trade_orders import create_trade_order
from app.services.trade_receipts import list_trade_receipts


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def _write_events(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines), encoding="utf-8")


def test_receipts_ingest_updates_order_and_fills(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr(settings, "data_root", str(tmp_path))

    result = create_trade_order(
        session,
        {
            "client_order_id": "manual-1",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
            "params": {"client_order_id_auto": True},
        },
    )
    session.commit()
    order = result.order

    bridge_dir = tmp_path / "lean_bridge" / f"direct_{order.id}"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    events_path = bridge_dir / "execution_events.jsonl"
    _write_events(
        events_path,
        [
            f'{{"order_id":1,"symbol":"AAPL","status":"Submitted","filled":0,"fill_price":0,"direction":"Buy","time":"2026-01-28T19:25:00Z","tag":"direct:{order.id}"}}',
            f'{{"order_id":1,"symbol":"AAPL","status":"Filled","filled":1,"fill_price":255.28,"direction":"Buy","time":"2026-01-28T19:25:01Z","tag":"direct:{order.id}"}}',
        ],
    )

    page = list_trade_receipts(session, limit=50, offset=0, mode="all")

    refreshed = session.get(TradeOrder, order.id)
    assert refreshed is not None
    assert refreshed.status == "FILLED"
    assert float(refreshed.filled_quantity or 0.0) == 1.0

    fills = session.query(TradeFill).filter(TradeFill.order_id == order.id).all()
    assert len(fills) == 1
    assert float(fills[0].fill_price) == 255.28
    assert fills[0].params
    assert fills[0].params.get("event_source") == "lean"

    assert page.items

    session.close()


def test_receipts_ingest_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr(settings, "data_root", str(tmp_path))

    result = create_trade_order(
        session,
        {
            "client_order_id": "manual-2",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
            "params": {"client_order_id_auto": True},
        },
    )
    session.commit()
    order = result.order

    bridge_dir = tmp_path / "lean_bridge" / f"direct_{order.id}"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    events_path = bridge_dir / "execution_events.jsonl"
    _write_events(
        events_path,
        [
            f'{{"order_id":1,"symbol":"AAPL","status":"Filled","filled":1,"fill_price":255.28,"direction":"Buy","time":"2026-01-28T19:25:01Z","tag":"direct:{order.id}"}}',
        ],
    )

    list_trade_receipts(session, limit=50, offset=0, mode="all")
    list_trade_receipts(session, limit=50, offset=0, mode="all")

    fills = session.query(TradeFill).filter(TradeFill.order_id == order.id).all()
    assert len(fills) == 1

    session.close()


def test_receipts_ingest_reject_updates_reason(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr(settings, "data_root", str(tmp_path))

    result = create_trade_order(
        session,
        {
            "client_order_id": "manual-3",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
            "params": {"client_order_id_auto": True},
        },
    )
    session.commit()
    order = result.order

    bridge_dir = tmp_path / "lean_bridge" / f"direct_{order.id}"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    events_path = bridge_dir / "execution_events.jsonl"
    _write_events(
        events_path,
        [
            f'{{"order_id":1,"symbol":"AAPL","status":"Rejected","filled":0,"fill_price":0,"direction":"Buy","time":"2026-01-28T19:25:01Z","tag":"direct:{order.id}","reason":"risk_block"}}',
        ],
    )

    list_trade_receipts(session, limit=50, offset=0, mode="all")

    refreshed = session.get(TradeOrder, order.id)
    assert refreshed is not None
    assert refreshed.status == "REJECTED"
    assert refreshed.params
    assert refreshed.params.get("reason") == "risk_block"

    session.close()
