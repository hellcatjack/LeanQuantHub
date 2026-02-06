from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project
from app.services import project_symbols


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_collect_active_project_symbols_includes_risk_off_symbols(monkeypatch):
    session = _make_session()
    try:
        session.add(Project(name="p1", description=None, is_archived=False))
        session.commit()

        cfg = {
            "benchmark": "SPY",
            "backtest_params": {
                "risk_off_symbols": " vgsh, ief, gld , tlt ",
            },
        }
        monkeypatch.setattr(
            project_symbols,
            "_resolve_project_config",
            lambda *_args, **_kwargs: cfg,
        )

        symbols, benchmarks = project_symbols.collect_active_project_symbols(session)

        assert set(symbols) == {"SPY", "VGSH", "IEF", "GLD", "TLT"}
        assert benchmarks == ["SPY"]
    finally:
        session.close()


def test_collect_active_project_symbols_includes_risk_off_symbol_fallback(monkeypatch):
    session = _make_session()
    try:
        session.add(Project(name="p1", description=None, is_archived=False))
        session.commit()

        cfg = {
            "benchmark": "SPY",
            "backtest_params": {
                "risk_off_symbols": "",
                "risk_off_symbol": "vgsh",
            },
        }
        monkeypatch.setattr(
            project_symbols,
            "_resolve_project_config",
            lambda *_args, **_kwargs: cfg,
        )

        symbols, benchmarks = project_symbols.collect_active_project_symbols(session)

        assert set(symbols) == {"SPY", "VGSH"}
        assert benchmarks == ["SPY"]
    finally:
        session.close()

