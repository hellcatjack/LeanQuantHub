from datetime import datetime, timezone
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeOrder, TradeFill
from app.services.realized_pnl import compute_realized_pnl


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_fifo_realized_pnl_with_commission():
    session = _make_session()
    try:
        baseline = {
            "created_at": "2026-01-30T00:00:00Z",
            "items": [{"symbol": "AAPL", "position": 10, "avg_cost": 100.0}],
        }

        order = TradeOrder(
            run_id=None,
            client_order_id="oi_0_0_1",
            symbol="AAPL",
            side="SELL",
            quantity=6,
            order_type="MKT",
            status="FILLED",
            filled_quantity=6,
            avg_fill_price=110.0,
        )
        session.add(order)
        session.flush()
        fill = TradeFill(
            order_id=order.id,
            fill_quantity=6,
            fill_price=110.0,
            commission=1.2,
            fill_time=datetime(2026, 1, 30, 0, 1, tzinfo=timezone.utc),
        )
        session.add(fill)
        session.commit()

        result = compute_realized_pnl(session, baseline)
        expected = (110 - 100) * 6 - 1.2
        assert round(result.symbol_totals["AAPL"], 6) == round(expected, 6)
        assert round(result.fill_totals[fill.id], 6) == round(expected, 6)
        assert round(result.order_totals[order.id], 6) == round(expected, 6)
    finally:
        session.close()


def test_realized_pnl_accepts_naive_fill_time():
    session = _make_session()
    try:
        baseline = {
            "created_at": "2026-01-30T00:00:00Z",
            "items": [{"symbol": "AAPL", "position": 5, "avg_cost": 100.0}],
        }

        order = TradeOrder(
            run_id=None,
            client_order_id="oi_0_0_2",
            symbol="AAPL",
            side="SELL",
            quantity=2,
            order_type="MKT",
            status="FILLED",
            filled_quantity=2,
            avg_fill_price=110.0,
        )
        session.add(order)
        session.flush()
        fill = TradeFill(
            order_id=order.id,
            fill_quantity=2,
            fill_price=110.0,
            commission=0.4,
            fill_time=datetime(2026, 1, 30, 0, 1),
        )
        session.add(fill)
        session.commit()

        result = compute_realized_pnl(session, baseline)
        expected = (110 - 100) * 2 - 0.4
        assert round(result.symbol_totals["AAPL"], 6) == round(expected, 6)
        assert round(result.fill_totals[fill.id], 6) == round(expected, 6)
        assert round(result.order_totals[order.id], 6) == round(expected, 6)
    finally:
        session.close()
