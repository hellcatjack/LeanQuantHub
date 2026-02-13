from datetime import datetime, timezone
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeOrder, TradeFill
import app.services.realized_pnl as realized_pnl
from app.services.realized_pnl import compute_realized_pnl


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def setup_function():
    realized_pnl.clear_realized_pnl_cache()


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


def test_realized_pnl_cache_reuses_rows_when_revision_unchanged(monkeypatch):
    session = _make_session()
    try:
        baseline = {
            "created_at": "2026-01-30T00:00:00Z",
            "items": [{"symbol": "AAPL", "position": 10, "avg_cost": 100.0}],
        }

        order = TradeOrder(
            run_id=None,
            client_order_id="oi_0_0_cache1",
            symbol="AAPL",
            side="SELL",
            quantity=1,
            order_type="MKT",
            status="FILLED",
            filled_quantity=1,
            avg_fill_price=110.0,
        )
        session.add(order)
        session.flush()
        fill = TradeFill(
            order_id=order.id,
            fill_quantity=1,
            fill_price=110.0,
            commission=0.1,
            fill_time=datetime(2026, 1, 30, 0, 2, tzinfo=timezone.utc),
        )
        session.add(fill)
        session.commit()

        calls = {"count": 0}
        original_query = realized_pnl._query_fill_rows

        def _spy_query(session_obj, *, baseline_at, symbols=None):
            calls["count"] += 1
            return original_query(session_obj, baseline_at=baseline_at, symbols=symbols)

        monkeypatch.setattr(realized_pnl, "_query_fill_rows", _spy_query)

        first = compute_realized_pnl(session, baseline, cache_ttl_seconds=60.0)
        second = compute_realized_pnl(session, baseline, cache_ttl_seconds=60.0)

        assert calls["count"] == 1
        assert first.order_totals == second.order_totals
    finally:
        session.close()


def test_realized_pnl_cache_invalidates_when_new_fill_arrives(monkeypatch):
    session = _make_session()
    try:
        baseline = {
            "created_at": "2026-01-30T00:00:00Z",
            "items": [{"symbol": "AAPL", "position": 10, "avg_cost": 100.0}],
        }

        order1 = TradeOrder(
            run_id=None,
            client_order_id="oi_0_0_cache2",
            symbol="AAPL",
            side="SELL",
            quantity=2,
            order_type="MKT",
            status="FILLED",
            filled_quantity=2,
            avg_fill_price=110.0,
        )
        session.add(order1)
        session.flush()
        session.add(
            TradeFill(
                order_id=order1.id,
                fill_quantity=2,
                fill_price=110.0,
                commission=0.2,
                fill_time=datetime(2026, 1, 30, 0, 3, tzinfo=timezone.utc),
            )
        )
        session.commit()

        calls = {"count": 0}
        original_query = realized_pnl._query_fill_rows

        def _spy_query(session_obj, *, baseline_at, symbols=None):
            calls["count"] += 1
            return original_query(session_obj, baseline_at=baseline_at, symbols=symbols)

        monkeypatch.setattr(realized_pnl, "_query_fill_rows", _spy_query)

        first = compute_realized_pnl(session, baseline, cache_ttl_seconds=60.0)
        first_total = first.symbol_totals.get("AAPL", 0.0)
        assert first_total > 0
        assert calls["count"] == 1

        order2 = TradeOrder(
            run_id=None,
            client_order_id="oi_0_0_cache3",
            symbol="AAPL",
            side="SELL",
            quantity=1,
            order_type="MKT",
            status="FILLED",
            filled_quantity=1,
            avg_fill_price=108.0,
        )
        session.add(order2)
        session.flush()
        session.add(
            TradeFill(
                order_id=order2.id,
                fill_quantity=1,
                fill_price=108.0,
                commission=0.1,
                fill_time=datetime(2026, 1, 30, 0, 4, tzinfo=timezone.utc),
            )
        )
        session.commit()

        second = compute_realized_pnl(session, baseline, cache_ttl_seconds=60.0)
        assert calls["count"] == 2
        assert second.symbol_totals.get("AAPL", 0.0) > first_total
    finally:
        session.close()


def test_realized_pnl_supports_symbol_scoped_computation():
    session = _make_session()
    try:
        baseline = {
            "created_at": "2026-01-30T00:00:00Z",
            "items": [
                {"symbol": "AAPL", "position": 10, "avg_cost": 100.0},
                {"symbol": "MSFT", "position": 8, "avg_cost": 200.0},
            ],
        }

        aapl_order = TradeOrder(
            run_id=None,
            client_order_id="oi_symbol_scope_aapl",
            symbol="AAPL",
            side="SELL",
            quantity=2,
            order_type="MKT",
            status="FILLED",
            filled_quantity=2,
            avg_fill_price=110.0,
        )
        msft_order = TradeOrder(
            run_id=None,
            client_order_id="oi_symbol_scope_msft",
            symbol="MSFT",
            side="SELL",
            quantity=3,
            order_type="MKT",
            status="FILLED",
            filled_quantity=3,
            avg_fill_price=210.0,
        )
        session.add_all([aapl_order, msft_order])
        session.flush()
        session.add_all(
            [
                TradeFill(
                    order_id=aapl_order.id,
                    fill_quantity=2,
                    fill_price=110.0,
                    commission=0.2,
                    fill_time=datetime(2026, 1, 30, 0, 5, tzinfo=timezone.utc),
                ),
                TradeFill(
                    order_id=msft_order.id,
                    fill_quantity=3,
                    fill_price=210.0,
                    commission=0.3,
                    fill_time=datetime(2026, 1, 30, 0, 6, tzinfo=timezone.utc),
                ),
            ]
        )
        session.commit()

        scoped = compute_realized_pnl(session, baseline, symbols={"AAPL"})

        assert "AAPL" in scoped.symbol_totals
        assert "MSFT" not in scoped.symbol_totals
        assert aapl_order.id in scoped.order_totals
        assert msft_order.id not in scoped.order_totals
    finally:
        session.close()
