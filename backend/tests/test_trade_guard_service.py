from datetime import date
import json
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeGuardState, TradeOrder, TradeRun, TradeFill, TradeSettings
import app.services.trade_guard as trade_guard
from app.services.trade_guard import evaluate_intraday_guard


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def _seed_position(session):
    run = TradeRun(project_id=1, mode="paper", status="done", params={"portfolio_value": 1000})
    session.add(run)
    session.flush()
    order = TradeOrder(
        run_id=run.id,
        client_order_id="run-1-SPY",
        symbol="SPY",
        side="BUY",
        quantity=10,
        status="FILLED",
    )
    session.add(order)
    session.flush()
    fill = TradeFill(order_id=order.id, fill_quantity=10, fill_price=100)
    session.add(fill)
    session.commit()
    return run


def test_guard_triggers_daily_loss():
    session = _make_session()
    try:
        _seed_position(session)
        state = TradeGuardState(
            project_id=1,
            trade_date=date(2026, 1, 17),
            mode="paper",
            day_start_equity=1000,
            equity_peak=1000,
            last_equity=1000,
        )
        session.add(state)
        session.commit()
        settings = TradeSettings(risk_defaults={"max_daily_loss": -0.05})
        session.add(settings)
        session.commit()

        result = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"max_daily_loss": -0.05},
            price_map={"SPY": 90.0},
            trade_date=date(2026, 1, 17),
        )
        assert result["status"] == "halted"
    finally:
        session.close()


def test_guard_skips_market_fetch_without_positions(monkeypatch):
    session = _make_session()

    def _boom(*args, **kwargs):
        raise AssertionError("market fetch called")

    monkeypatch.setattr(trade_guard, "fetch_market_snapshots", _boom)
    try:
        result = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"cash_available": 1000},
        )
        assert result["status"] == "active"
    finally:
        session.close()


def test_read_local_snapshot_reads_bridge_cache(tmp_path, monkeypatch):
    from app.services import lean_bridge

    cache_root = tmp_path / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    (cache_root / "quotes.json").write_text(
        json.dumps([{"symbol": "SPY", "last": 10}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(lean_bridge, "CACHE_ROOT", cache_root, raising=False)
    assert trade_guard._read_local_snapshot("SPY") == {"symbol": "SPY", "last": 10}
