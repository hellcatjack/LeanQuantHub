from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, PitWeeklyJob, PitFundamentalJob
from app.routes import pit as pit_routes


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_pit_weekly_jobs_page(monkeypatch):
    session = _make_session()

    for idx in range(12):
        session.add(PitWeeklyJob(status="queued", params={"i": idx}))
    session.commit()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(pit_routes, "get_session", _get_session)

    resp = pit_routes.list_weekly_jobs_page(page=2, page_size=5)
    dumped = resp.model_dump()
    assert dumped["total"] == 12
    assert dumped["page"] == 2
    assert dumped["page_size"] == 5
    assert len(dumped["items"]) == 5

    session.close()
