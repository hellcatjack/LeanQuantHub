from pathlib import Path
import sys
import tempfile

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, DecisionSnapshot, TradeFill, TradeOrder, TradeRun
from app.services.trade_run_summary import build_symbol_summary


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_symbol_summary_aggregates():
    session = _make_session()
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    try:
        tmp_file.write(b"symbol,weight\nSPY,0.1\n")
        tmp_file.close()
        snapshot = DecisionSnapshot(project_id=1, status="success", items_path=tmp_file.name)
        session.add(snapshot)
        session.commit()
        run = TradeRun(
            project_id=1,
            decision_snapshot_id=snapshot.id,
            mode="paper",
            status="queued",
            params={"portfolio_value": 1000},
        )
        session.add(run)
        session.commit()
        order = TradeOrder(
            run_id=run.id,
            client_order_id="run-1-SPY-BUY",
            symbol="SPY",
            side="BUY",
            quantity=1,
            order_type="MKT",
            status="NEW",
        )
        session.add(order)
        session.commit()
        fill = TradeFill(
            order_id=order.id,
            fill_quantity=1,
            fill_price=10,
            exec_id="X1",
        )
        session.add(fill)
        session.commit()

        summary = build_symbol_summary(session, run.id)
        assert any(row["symbol"] == "SPY" for row in summary)
        spy = next(row for row in summary if row["symbol"] == "SPY")
        assert spy["target_weight"] == 0.1
        assert spy["filled_qty"] == 1
    finally:
        Path(tmp_file.name).unlink(missing_ok=True)
        session.close()
