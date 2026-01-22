from pathlib import Path
import csv
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, DecisionSnapshot
import app.services.ib_stream as ib_stream


def _make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def _write_items(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "weight", "score", "rank"])
        writer.writeheader()
        writer.writerow({"symbol": "AAPL", "weight": "0.1", "score": "0.9", "rank": "1"})
        writer.writerow({"symbol": "NVDA", "weight": "0.2", "score": "1.1", "rank": "2"})


def test_stream_symbols_prefers_snapshot(tmp_path):
    Session = _make_session_factory()
    session = Session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "decision_items.csv"
        _write_items(items_path)
        snapshot = DecisionSnapshot(
            project_id=project.id,
            status="success",
            items_path=str(items_path),
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        symbols = ib_stream.build_stream_symbols(
            session,
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
        )
        assert symbols == ["AAPL", "NVDA"]
    finally:
        session.close()
