from datetime import datetime, timedelta
from pathlib import Path
import json
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import ib_stream


def test_snapshot_ttl_respects_symbols_and_time(tmp_path):
    stream_root = tmp_path / "ib" / "stream"
    stream_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "ok",
        "last_heartbeat": (datetime.utcnow() - timedelta(seconds=5)).isoformat() + "Z",
        "subscribed_symbols": ["SPY", "AAPL"],
        "ib_error_count": 0,
        "last_error": None,
        "market_data_type": "realtime",
    }
    (stream_root / "_status.json").write_text(json.dumps(payload), encoding="utf-8")

    assert ib_stream.is_snapshot_fresh(stream_root, ["SPY", "AAPL"], ttl_seconds=30) is True
    assert ib_stream.is_snapshot_fresh(stream_root, ["SPY"], ttl_seconds=30) is False
    assert ib_stream.is_snapshot_fresh(stream_root, ["SPY", "AAPL"], ttl_seconds=1) is False
