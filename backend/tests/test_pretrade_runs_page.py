from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, PreTradeRun, Project
from app.routes import pretrade as pretrade_routes


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_pretrade_runs_page_filters_project(monkeypatch):
    session = _make_session()

    project_a = Project(name="p-a", description="")
    project_b = Project(name="p-b", description="")
    session.add_all([project_a, project_b])
    session.commit()
    session.refresh(project_a)
    session.refresh(project_b)

    for _ in range(7):
        session.add(PreTradeRun(project_id=project_a.id, status="queued"))
    for _ in range(3):
        session.add(PreTradeRun(project_id=project_b.id, status="queued"))
    session.commit()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(pretrade_routes, "get_session", _get_session)

    resp = pretrade_routes.list_pretrade_runs_page(project_id=project_a.id, page=1, page_size=5)
    dumped = resp.model_dump()
    assert dumped["total"] == 7
    assert dumped["page_size"] == 5
    assert len(dumped["items"]) == 5

    session.close()
