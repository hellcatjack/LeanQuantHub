from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models import Base
from app.services import trade_direct_order


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_direct_order_uses_worker_client_id(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))

    captured = {}

    def _fake_build_execution_config(**kwargs):
        captured["client_id"] = kwargs.get("client_id")
        return {"lean-bridge-output-dir": kwargs.get("lean_bridge_output_dir")}

    monkeypatch.setattr(trade_direct_order, "build_execution_config", _fake_build_execution_config)
    monkeypatch.setattr(trade_direct_order, "launch_execution_async", lambda *_args, **_kwargs: 4321)
    monkeypatch.setattr(trade_direct_order, "lease_client_id", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("lease_client_id should not be called")))
    monkeypatch.setattr(trade_direct_order, "_select_worker", lambda *_args, **_kwargs: 2001)

    session = _make_session()
    payload = {
        "project_id": 1,
        "mode": "paper",
        "client_order_id": "manual-1",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "order_type": "MKT",
        "params": {"client_order_id_auto": True},
    }
    result = trade_direct_order.submit_direct_order(session, payload)
    assert result.execution_status == "submitted_lean"
    assert captured["client_id"] == 2001
