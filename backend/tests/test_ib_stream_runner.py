from pathlib import Path
from datetime import datetime, timedelta
import json
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.services.ib_stream as ib_stream


def test_stream_runner_mock_writes_files(tmp_path):
    runner = ib_stream.IBStreamRunner(project_id=1, data_root=tmp_path, api_mode="mock")
    runner._write_tick("SPY", {"last": 480.0})
    payload_path = tmp_path / "stream" / "SPY.json"
    assert payload_path.exists()
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["symbol"] == "SPY"
    assert payload["source"] == "mock"
    assert payload["last"] == 480.0


def test_stream_runner_writes_status(tmp_path):
    runner = ib_stream.IBStreamRunner(project_id=1, data_root=tmp_path, api_mode="mock")
    runner.write_status("connected", ["SPY"], market_data_type="delayed")
    status = runner.read_status()
    assert status["status"] == "connected"


def test_stream_runner_refreshes_snapshot_when_stale(tmp_path, monkeypatch):
    runner = ib_stream.IBStreamRunner(
        project_id=1,
        decision_snapshot_id=3,
        refresh_interval_seconds=5,
        stale_seconds=1,
        data_root=tmp_path,
        api_mode="mock",
    )
    runner._last_tick_ts["SPY"] = datetime.utcnow() - timedelta(seconds=10)

    def _fake_snapshots(*args, **kwargs):
        return [{"symbol": "SPY", "data": {"last": 101.0}}]

    monkeypatch.setattr(ib_stream, "fetch_market_snapshots", _fake_snapshots)
    runner._refresh_snapshot_if_stale(["SPY"])

    payload = json.loads((tmp_path / "stream" / "SPY.json").read_text(encoding="utf-8"))
    assert payload["source"] == "ib_snapshot"
