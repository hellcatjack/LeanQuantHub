from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, PreTradeRun, TradeRun
from app.services.pipeline_aggregator import list_pipeline_runs


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_list_pipeline_runs_project_scoped():
    session = _make_session()
    session.add_all(
        [
            PreTradeRun(project_id=1, status="success"),
            PreTradeRun(project_id=2, status="success"),
            TradeRun(project_id=1, status="queued", mode="paper", params={"source": "manual"}),
        ]
    )
    session.commit()

    runs = list_pipeline_runs(session, project_id=1)
    trace_ids = {item["trace_id"] for item in runs}
    assert "pretrade:1" in trace_ids
    assert "trade:1" in trace_ids
    assert all(item["project_id"] == 1 for item in runs)
