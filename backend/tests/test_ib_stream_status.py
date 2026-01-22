from pathlib import Path
import json
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.services.ib_stream as ib_stream


def test_stream_status_written(tmp_path):
    status = ib_stream.write_stream_status(
        tmp_path,
        status="connected",
        symbols=["SPY"],
        market_data_type="delayed",
    )
    status_path = tmp_path / "_status.json"
    assert status_path.exists()
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["status"] == "connected"
    assert payload["subscribed_symbols"] == ["SPY"]
    assert payload["market_data_type"] == "delayed"


def test_stream_config_roundtrip(tmp_path):
    config = {
        "project_id": 1,
        "decision_snapshot_id": 10,
        "max_symbols": 50,
        "market_data_type": "delayed",
        "refresh_interval_seconds": 30,
    }
    ib_stream.write_stream_config(tmp_path, config)
    loaded = ib_stream.read_stream_config(tmp_path)
    assert loaded["project_id"] == 1
    assert loaded["market_data_type"] == "delayed"
