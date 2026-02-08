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
from app.models import Base
from app.services.ib_orders import apply_fill_to_order
from app.services.trade_orders import create_trade_order
from app.services.trade_receipts import list_trade_receipts


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_trade_receipts_merge_db_and_lean(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr(settings, "data_root", str(tmp_path))

    result = create_trade_order(
        session,
        {
            "client_order_id": "manual-direct",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
            "params": {"client_order_id_auto": True},
        },
    )
    session.commit()
    order = result.order

    fill_time = datetime(2026, 1, 28, 10, 0, 0, tzinfo=timezone.utc)
    apply_fill_to_order(
        session,
        order,
        fill_qty=1,
        fill_price=100.0,
        fill_time=fill_time,
        exec_id="EXEC-1",
    )

    bridge_dir = tmp_path / "lean_bridge" / f"direct_{order.id}"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    events_path = bridge_dir / "execution_events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                '{"order_id": 1, "symbol": "AAPL", "status": "Submitted", "filled": 0, "fill_price": 0, "direction": "Buy", "time": "2026-01-28T09:59:00Z"}',
                '{"order_id": 1, "symbol": "AAPL", "status": "Filled", "filled": 1, "fill_price": 100, "direction": "Buy", "time": "2026-01-28T10:00:00Z"}',
            ]
        ),
        encoding="utf-8",
    )

    page = list_trade_receipts(session, limit=50, offset=0, mode="all")
    kinds = {(item.source, item.kind) for item in page.items}

    assert ("db", "order") in kinds
    assert ("db", "fill") in kinds
    assert ("lean", "submit") in kinds
    assert ("lean", "fill") not in kinds
    assert page.warnings == []

    session.close()


def test_trade_receipts_warn_missing_lean_logs(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr(settings, "data_root", str(tmp_path))

    page = list_trade_receipts(session, limit=50, offset=0, mode="all")

    assert page.items == []
    assert page.warnings == ["lean_logs_missing"]

    session.close()


def test_trade_receipts_sorted_by_order_id_desc(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    # Avoid warnings from missing lean_bridge root (sorting should still work, but keep the test clean).
    (tmp_path / "lean_bridge").mkdir(parents=True, exist_ok=True)

    create_trade_order(
        session,
        {
            "client_order_id": "manual-1",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
            "params": {"client_order_id_auto": True},
        },
    )
    create_trade_order(
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

    page = list_trade_receipts(session, limit=50, offset=0, mode="orders")

    assert [item.order_id for item in page.items] == sorted(
        [item.order_id for item in page.items], reverse=True
    )
    assert page.warnings == []

    session.close()
