from datetime import date, datetime
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, TradeGuardState, TradeRun
from app.services.trade_run_summary import build_trade_run_detail


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_build_trade_run_detail_includes_guard_currency_risk_audit():
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=None,
            mode="paper",
            status="blocked",
            params={
                "guard_precheck": {
                    "status": "halted",
                    "equity_source": "ib_net_liquidation",
                    "cashflow_adjustment": 260.0,
                    "dd_all": 0.12,
                    "dd_52w": 0.11,
                    "dd_lock_state": True,
                    "metrics": {
                        "pnl_total_by_currency": {"USD": 20.0, "EUR": 130.0},
                        "equity_source": "ib_net_liquidation",
                    },
                    "thresholds": {"max_drawdown": 0.1},
                    "trigger_details": [{"reason": "max_drawdown"}],
                    "reason": {"reasons": ["max_drawdown"]},
                }
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        guard_state = TradeGuardState(
            project_id=project.id,
            trade_date=date(2026, 2, 17),
            mode="paper",
            status="halted",
            valuation_source="ib_net_liquidation",
            halt_reason={"reasons": ["max_drawdown"]},
            updated_at=datetime(2026, 2, 17, 12, 0, 0),
        )
        session.add(guard_state)
        session.commit()

        _run, _orders, _fills, _updated, risk_audit = build_trade_run_detail(session, run.id)
        assert isinstance(risk_audit, dict)
        assert risk_audit.get("source") == "guard_precheck"
        assert risk_audit.get("cashflow_adjustment") == 260.0
        assert (risk_audit.get("pnl_total_by_currency") or {}).get("EUR") == 130.0
        assert (risk_audit.get("guard_state") or {}).get("status") == "halted"
    finally:
        session.close()


def test_build_trade_run_detail_returns_none_risk_audit_without_guard_data():
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=None,
            mode="paper",
            status="queued",
            params={},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        _run, _orders, _fills, _updated, risk_audit = build_trade_run_detail(session, run.id)
        assert risk_audit is None
    finally:
        session.close()
