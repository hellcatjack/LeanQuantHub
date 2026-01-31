from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.services import lean_bridge_reader


def test_bridge_status_not_stale_within_timeout(tmp_path, monkeypatch):
    bridge_root = tmp_path / "lean_bridge"
    bridge_root.mkdir(parents=True)
    heartbeat = datetime.now(timezone.utc) - timedelta(seconds=30)
    payload = {
        "status": "ok",
        "last_heartbeat": heartbeat.isoformat().replace("+00:00", "Z"),
    }
    (bridge_root / "lean_bridge_status.json").write_text(json.dumps(payload))

    monkeypatch.setattr(settings, "lean_bridge_heartbeat_timeout_seconds", 60)

    status = lean_bridge_reader.read_bridge_status(bridge_root)

    assert status.get("stale") is False
