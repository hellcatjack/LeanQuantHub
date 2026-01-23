from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, DecisionSnapshot
from app.routes import trade as trade_routes


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_create_trade_run_uses_latest_snapshot(monkeypatch):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        snapshot = DecisionSnapshot(project_id=project.id, status="success", items_path="/tmp/x.csv")
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        monkeypatch.setattr(trade_routes, "check_market_health", lambda *_a, **_k: {"status": "ok"})

        payload = trade_routes.TradeRunCreate(
            project_id=project.id,
            decision_snapshot_id=None,
            mode="paper",
            orders=[
                trade_routes.TradeOrderCreate(
                    client_order_id="c1",
                    symbol="SPY",
                    side="BUY",
                    quantity=1,
                    order_type="MKT",
                )
            ],
            require_market_health=False,
        )
        result = trade_routes.create_trade_run(payload)
        assert result.decision_snapshot_id == snapshot.id
    finally:
        session.close()
