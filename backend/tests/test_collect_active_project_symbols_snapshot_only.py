from datetime import datetime
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, DecisionSnapshot, Project
from app.services import project_symbols


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_collect_active_project_symbols_uses_latest_snapshot_and_risk_off(monkeypatch, tmp_path):
    session = _make_session()
    try:
        project = Project(name="p1", description=None, is_archived=False)
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "snapshot_items.csv"
        items_path.write_text("symbol\nAAPL\nMSFT\n", encoding="utf-8")
        session.add(
            DecisionSnapshot(
                project_id=int(project.id),
                status="success",
                items_path=str(items_path),
                created_at=datetime.utcnow(),
            )
        )
        session.commit()

        cfg = {
            "benchmark": "SPY",
            "themes": [{"key": "irrelevant", "weight": 1.0}],
            "backtest_params": {"risk_off_symbols": "VGSH,IEF,GLD,TLT"},
        }
        monkeypatch.setattr(
            project_symbols,
            "_resolve_project_config",
            lambda *_args, **_kwargs: cfg,
        )
        monkeypatch.setattr(
            project_symbols,
            "collect_project_symbols",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("collect_project_symbols should not be called")
            ),
        )

        symbols, benchmarks = project_symbols.collect_active_project_symbols(session)

        assert set(symbols) == {"SPY", "AAPL", "MSFT", "VGSH", "IEF", "GLD", "TLT"}
        assert benchmarks == ["SPY"]
    finally:
        session.close()

