from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import SessionLocal
from app.services import ib_status_overview


def test_ib_status_overview_shape():
    session = SessionLocal()
    try:
        data = ib_status_overview.build_ib_status_overview(session)
    finally:
        session.close()
    assert "connection" in data
    assert "config" in data
    assert "stream" in data
    assert "snapshot_cache" in data
    assert "orders" in data
    assert "alerts" in data
    assert "refreshed_at" in data
