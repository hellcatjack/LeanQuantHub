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


def test_read_positions_marks_stale_when_snapshot_old(tmp_path):
    bridge_root = tmp_path / "lean_bridge"
    bridge_root.mkdir(parents=True)
    refreshed_at = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat().replace(
        "+00:00", "Z"
    )
    payload = {
        "items": [{"symbol": "AAA", "quantity": 1}],
        "source": "lean_bridge",
        "source_detail": "ib_holdings",
        "refreshed_at": refreshed_at,
    }
    (bridge_root / "positions.json").write_text(json.dumps(payload), encoding="utf-8")

    positions = lean_bridge_reader.read_positions(bridge_root)
    assert positions.get("stale") is True


def test_read_positions_not_stale_when_snapshot_recent(tmp_path):
    bridge_root = tmp_path / "lean_bridge"
    bridge_root.mkdir(parents=True)
    refreshed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "items": [{"symbol": "AAA", "quantity": 1}],
        "source": "lean_bridge",
        "source_detail": "ib_holdings",
        "refreshed_at": refreshed_at,
    }
    (bridge_root / "positions.json").write_text(json.dumps(payload), encoding="utf-8")

    positions = lean_bridge_reader.read_positions(bridge_root)
    assert positions.get("stale") is False


def test_read_open_orders_includes_bridge_client_id(tmp_path):
    bridge_root = tmp_path / "lean_bridge"
    bridge_root.mkdir(parents=True)
    refreshed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    open_orders_payload = {
        "items": [{"tag": "direct:1", "symbol": "AAPL"}],
        "source_detail": "ib_open_orders",
        "refreshed_at": refreshed_at,
    }
    process_payload = {"pid": 123, "client_id": 0, "mode": "paper"}
    (bridge_root / "open_orders.json").write_text(json.dumps(open_orders_payload), encoding="utf-8")
    (bridge_root / "bridge_process.json").write_text(json.dumps(process_payload), encoding="utf-8")

    payload = lean_bridge_reader.read_open_orders(bridge_root)

    assert payload.get("stale") is False
    assert payload.get("bridge_client_id") == 0
