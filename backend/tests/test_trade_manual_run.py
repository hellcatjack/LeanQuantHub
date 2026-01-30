from contextlib import contextmanager
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, TradeOrder, TradeRun
from app.routes import trade as trade_routes


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_manual_trade_run_writes_intent(monkeypatch, tmp_path):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        monkeypatch.setattr(trade_routes.trade_executor, "ARTIFACT_ROOT", tmp_path, raising=False)

        captured = {}

        def _execute(run_id: int, dry_run: bool = False, force: bool = False):
            captured["run_id"] = run_id
            captured["dry_run"] = dry_run
            captured["force"] = force
            return SimpleNamespace(
                run_id=run_id,
                status="running",
                filled=0,
                cancelled=0,
                rejected=0,
                skipped=0,
                message="submitted_lean",
                dry_run=dry_run,
            )

        monkeypatch.setattr(trade_routes, "execute_trade_run", _execute)

        payload = trade_routes.TradeManualRunCreate(
            project_id=project.id,
            mode="paper",
            orders=[
                trade_routes.TradeManualOrderCreate(
                    symbol="AAPL",
                    side="SELL",
                    quantity=1,
                    order_type="MKT",
                )
            ],
        )

        result = trade_routes.create_manual_trade_run(payload)
        assert result.run_id == captured["run_id"]
        assert captured["force"] is True

        run = session.get(TradeRun, result.run_id)
        assert run is not None
        params = run.params or {}
        assert params.get("source") == "manual"
        assert params.get("risk_bypass") is True
        intent_path = Path(params.get("order_intent_path") or "")
        assert intent_path.exists()

        intent_payload = json.loads(intent_path.read_text(encoding="utf-8"))
        assert intent_payload[0]["order_intent_id"] == f"oi_{run.id}_0"
        assert intent_payload[0]["quantity"] == -1.0

        orders = session.query(TradeOrder).filter(TradeOrder.run_id == run.id).all()
        assert len(orders) == 1
        assert orders[0].client_order_id == f"oi_{run.id}_0"
        assert orders[0].side == "SELL"
        assert orders[0].quantity == 1.0
    finally:
        session.close()
