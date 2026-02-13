from pathlib import Path
import sys
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, TradeOrder, TradeRun, TradeSettings
from app.services import trade_executor


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


class _DummyLock:
    def __init__(self, *args, **kwargs):
        pass

    def acquire(self):
        return True

    def release(self):
        return None


def test_execute_trade_run_uses_async_lean_launcher(monkeypatch, tmp_path):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p18", description=""))
        session.commit()

        settings = TradeSettings(risk_defaults={}, execution_data_source="lean", auto_recovery={})
        session.add(settings)
        session.commit()

        intent_path = tmp_path / "intent.json"
        intent_path.write_text(json.dumps([{"symbol": "AAPL", "quantity": 1, "weight": 0}]), encoding="utf-8")
        params_path = tmp_path / "params.json"
        params_path.write_text(json.dumps({"min_qty": 1, "lot_size": 1, "unfilled_timeout_seconds": 60}), encoding="utf-8")

        run = TradeRun(
            project_id=1,
            decision_snapshot_id=1,
            mode="paper",
            status="queued",
            params={
                "order_intent_path": str(intent_path),
                "execution_params_path": str(params_path),
                "risk_bypass": True,
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        order = TradeOrder(
            run_id=run.id,
            client_order_id="test:1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="MKT",
            status="NEW",
        )
        session.add(order)
        session.commit()

        called = {"config_path": None}

        def _fake_launch_execution_async(*, config_path: str) -> int:
            called["config_path"] = config_path
            return 4242

        monkeypatch.setattr(trade_executor, "SessionLocal", Session, raising=False)
        monkeypatch.setattr(trade_executor, "JobLock", _DummyLock, raising=False)
        monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda: True, raising=False)
        monkeypatch.setattr(trade_executor, "_build_price_map", lambda symbols: {"AAPL": 100.0}, raising=False)
        monkeypatch.setattr(trade_executor, "fetch_account_summary", lambda _session: {"NetLiquidation": 10000.0}, raising=False)
        monkeypatch.setattr(trade_executor, "launch_execution_async", _fake_launch_execution_async, raising=False)
        monkeypatch.setattr(trade_executor, "ARTIFACT_ROOT", tmp_path, raising=False)

        result = trade_executor.execute_trade_run(run.id, dry_run=False, force=False)
        assert result.status == "running"
        assert called["config_path"] is not None
        config_payload = json.loads(Path(called["config_path"]).read_text(encoding="utf-8"))
        assert config_payload.get("lean-bridge-exit-on-submit") is False

        session.expire_all()
        refreshed = session.get(TradeRun, run.id)
        assert refreshed is not None
        assert refreshed.message == "submitted_lean"
        assert isinstance(refreshed.params, dict)
        assert refreshed.params["lean_execution"]["pid"] == 4242
    finally:
        session.close()
