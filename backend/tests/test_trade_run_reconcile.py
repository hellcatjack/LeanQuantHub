from pathlib import Path
import json
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeFill, TradeRun, TradeOrder
from app.services import trade_executor
from app.services.trade_orders import create_trade_order, update_trade_order_status


def _make_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _write_intent(tmp_path: Path, symbols: list[str]) -> str:
    items = []
    for idx, symbol in enumerate(symbols):
        items.append({"order_intent_id": f"oi_1_{idx}", "symbol": symbol})
    path = tmp_path / "order_intent.json"
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_reconcile_run_with_positions_marks_filled():
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        run = TradeRun(
            project_id=1,
            status="running",
            mode="paper",
            params={
                "positions_baseline": {
                    "refreshed_at": "2026-02-07T00:00:00Z",
                    "items": [{"symbol": "AAPL", "quantity": 0.0}],
                }
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        payload = {
            "client_order_id": "oi_1_0_1",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
        }
        result = create_trade_order(session, payload, run_id=run.id)
        session.commit()

        positions_payload = {
            "items": [
                {
                    "symbol": "AAPL",
                    "quantity": 1.0,
                    "avg_cost": 100.0,
                }
            ]
        }

        trade_executor.reconcile_run_with_positions(session, run, positions_payload)
        trade_executor.reconcile_run_with_positions(session, run, positions_payload)

        session.refresh(result.order)
        assert result.order.status == "FILLED"
        assert result.order.filled_quantity == 1
        assert result.order.avg_fill_price == 100.0
        fills = session.query(TradeFill).filter(TradeFill.order_id == result.order.id).all()
        assert len(fills) == 1
    finally:
        session.close()


def test_force_close_run_cancels_open_orders():
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        run = TradeRun(project_id=1, status="running", mode="paper")
        session.add(run)
        session.commit()
        session.refresh(run)

        payload = {
            "client_order_id": "oi_1_0_2",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 2,
            "order_type": "MKT",
        }
        new_order = create_trade_order(session, payload, run_id=run.id).order
        session.commit()

        partial_order = create_trade_order(
            session,
            {**payload, "client_order_id": "oi_1_0_3", "symbol": "MSFT"},
            run_id=run.id,
        ).order
        session.commit()
        update_trade_order_status(session, partial_order, {"status": "SUBMITTED"})
        update_trade_order_status(
            session,
            partial_order,
            {"status": "PARTIAL", "filled_quantity": 1, "avg_fill_price": 100},
        )

        filled_order = create_trade_order(
            session,
            {**payload, "client_order_id": "oi_1_0_4", "symbol": "NVDA"},
            run_id=run.id,
        ).order
        session.commit()
        update_trade_order_status(session, filled_order, {"status": "SUBMITTED"})
        update_trade_order_status(
            session,
            filled_order,
            {"status": "FILLED", "filled_quantity": 2, "avg_fill_price": 200},
        )

        trade_executor.force_close_run(session, run, reason="test_force_close")

        session.refresh(run)
        session.refresh(new_order)
        session.refresh(partial_order)
        session.refresh(filled_order)

        assert run.status == "failed"
        assert run.ended_at is not None
        assert new_order.status == "CANCELED"
        assert partial_order.status == "CANCELED"
        assert filled_order.status == "FILLED"
        summary = (run.params or {}).get("completion_summary")
        assert summary == {"total": 3, "filled": 1, "cancelled": 2, "rejected": 0}
    finally:
        session.close()


def test_enforce_intent_order_match_fails_on_missing(tmp_path: Path):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        run = TradeRun(project_id=1, status="queued", mode="paper", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        intent_path = _write_intent(tmp_path, ["AAPL", "MSFT"])
        run.params = {"order_intent_path": intent_path}
        session.commit()

        payload = {
            "client_order_id": "oi_1_0_2",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
        }
        create_trade_order(session, payload, run_id=run.id)
        session.commit()

        orders = session.query(TradeOrder).filter(TradeOrder.run_id == run.id).all()
        ok = trade_executor.enforce_intent_order_match(session, run, orders, intent_path)
        assert ok is False

        session.refresh(run)
        assert run.status == "failed"
        assert run.message == "intent_order_mismatch"
        assert all(
            order.status == "CANCELED"
            for order in session.query(TradeOrder).filter(TradeOrder.run_id == run.id).all()
        )
        mismatch = (run.params or {}).get("intent_order_mismatch") or {}
        assert mismatch.get("missing_symbols") == ["MSFT"]
    finally:
        session.close()
