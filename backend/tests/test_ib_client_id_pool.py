from datetime import datetime, timedelta
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models import Base
from app.services import ib_client_id_pool


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_lease_client_id_allocates_unique(monkeypatch):
    monkeypatch.setattr(settings, "ib_client_id_pool_base", 900)
    monkeypatch.setattr(settings, "ib_client_id_pool_size", 2)
    monkeypatch.setattr(settings, "ib_client_id_live_offset", 5000)

    session = _make_session()
    lease1 = ib_client_id_pool.lease_client_id(session, order_id=1, mode="paper", output_dir="/tmp/a")
    lease2 = ib_client_id_pool.lease_client_id(session, order_id=2, mode="paper", output_dir="/tmp/b")
    assert lease1.client_id != lease2.client_id


def test_lease_client_id_pool_exhausted(monkeypatch):
    monkeypatch.setattr(settings, "ib_client_id_pool_base", 900)
    monkeypatch.setattr(settings, "ib_client_id_pool_size", 1)

    session = _make_session()
    ib_client_id_pool.lease_client_id(session, order_id=1, mode="paper", output_dir="/tmp/a")
    try:
        ib_client_id_pool.lease_client_id(session, order_id=2, mode="paper", output_dir="/tmp/b")
        assert False, "expected ClientIdPoolExhausted"
    except ib_client_id_pool.ClientIdPoolExhausted:
        assert True


def test_reap_stale_leases_releases(monkeypatch):
    monkeypatch.setattr(settings, "ib_client_id_pool_base", 900)
    monkeypatch.setattr(settings, "ib_client_id_pool_size", 1)
    monkeypatch.setattr(settings, "ib_client_id_lease_ttl_seconds", 1)
    monkeypatch.setattr(settings, "lean_bridge_heartbeat_timeout_seconds", 1)

    session = _make_session()
    lease = ib_client_id_pool.lease_client_id(session, order_id=1, mode="paper", output_dir="/tmp/a")
    lease.acquired_at = datetime.utcnow() - timedelta(seconds=10)
    session.commit()

    released = ib_client_id_pool.reap_stale_leases(session, mode="paper", now=datetime.utcnow())
    assert released == 1
