from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys

from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models import Base
from app.routes import trade as trade_routes
from app.services.trade_orders import create_trade_order


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_trade_receipts_total_count_header(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr(settings, "data_root", str(tmp_path))

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    trade_routes.get_session = _get_session  # type: ignore[attr-defined]

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
    session.commit()

    response = Response()
    result = trade_routes.list_trade_receipts(limit=50, offset=0, mode="all", response=response)

    assert response.headers.get("X-Total-Count") == "1"
    assert result.total == 1
    assert len(result.items) == 1

    session.close()
