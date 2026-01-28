from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models import Base, IBClientIdPool
from app.services import trade_direct_order


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_submit_direct_order_allocates_client_id(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "ib_client_id_pool_base", 900)
    monkeypatch.setattr(settings, "ib_client_id_pool_size", 1)

    captured = {}

    def _fake_launch(config_path: str):
        captured["config_path"] = config_path
        return 4321

    monkeypatch.setattr(trade_direct_order, "launch_execution_async", _fake_launch)

    session = _make_session()
    payload = {
        "project_id": 1,
        "mode": "paper",
        "client_order_id": "manual-1",
        "symbol": "SPY",
        "side": "BUY",
        "quantity": 1,
        "order_type": "MKT",
        "params": {"client_order_id_auto": True},
    }
    result = trade_direct_order.submit_direct_order(session, payload)
    assert result.order_id > 0

    lease = session.query(IBClientIdPool).first()
    assert lease is not None
    assert lease.client_id == 900
    assert lease.pid == 4321
