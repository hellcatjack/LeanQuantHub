from pathlib import Path
import json
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.services.ib_stream as ib_stream
from app.services.ib_stream_runner import (
    StreamRunConfig,
    StreamSnapshotWriter,
    StreamStatusWriter,
)


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


def test_stream_snapshot_writer_writes_symbol_snapshot(tmp_path: Path):
    writer = StreamSnapshotWriter(tmp_path)
    writer.write_snapshot("SPY", {"last": 100.0, "timestamp": "2026-01-23T00:00:00Z"})
    assert (tmp_path / "SPY.json").exists()


def test_stream_status_writer_writes_status(tmp_path: Path):
    writer = StreamStatusWriter(tmp_path)
    writer.write_status(status="running", symbols=["SPY"], error=None, market_data_type="delayed")
    assert (tmp_path / "_status.json").exists()


def test_stream_run_config_defaults(tmp_path: Path):
    config = StreamRunConfig(stream_root=tmp_path, symbols=["SPY"], market_data_type="delayed")
    assert config.symbols == ["SPY"]
