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


def test_ib_stream_client_emits_ticks():
    events = []

    client = ib_stream.IBStreamClient("127.0.0.1", 4001, 1, lambda symbol, tick: events.append((symbol, tick)))
    client._req_map[1] = "SPY"
    client.tickPrice(1, 4, 123.0, None)
    client.tickSize(1, 5, 12)

    assert any(evt[0] == "SPY" and evt[1].get("last") == 123.0 for evt in events)
    assert any(evt[1].get("last_size") == 12 for evt in events)


def test_stream_runner_loop_writes_status(tmp_path):
    runner = ib_stream.IBStreamRunner(project_id=1, data_root=tmp_path, api_mode="mock")
    runner._write_status_update(["SPY"], market_data_type="delayed")
    status = ib_stream.get_stream_status(tmp_path)
    assert status["status"] in {"connected", "degraded"}


def test_stream_runner_writes_status_before_snapshot(tmp_path, monkeypatch):
    stream_root = tmp_path / "stream"
    stream_root.mkdir(parents=True, exist_ok=True)
    (stream_root / "_config.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "project_id": 1,
                "symbols": ["AAPL"],
                "market_data_type": "delayed",
                "refresh_interval_seconds": 5,
                "stale_seconds": 15,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    runner = ib_stream.IBStreamRunner(project_id=1, data_root=tmp_path, api_mode="mock")

    class DummySettings:
        api_mode = "mock"
        host = "127.0.0.1"
        port = 4001
        client_id = 1

    monkeypatch.setattr(ib_stream, "get_or_create_ib_settings", lambda session: DummySettings())
    monkeypatch.setattr(ib_stream, "SessionLocal", lambda: type("S", (), {"close": lambda self: None})())

    def _fake_refresh(symbols):
        status = ib_stream.get_stream_status(tmp_path)
        assert status["phase"] == "pre_snapshot"
        raise RuntimeError("stop")

    monkeypatch.setattr(runner, "_refresh_snapshot_if_stale", _fake_refresh)

    try:
        runner.run_forever()
    except RuntimeError as exc:
        assert str(exc) == "stop"


def test_stream_runner_records_snapshot_error(tmp_path, monkeypatch):
    stream_root = tmp_path / "stream"
    stream_root.mkdir(parents=True, exist_ok=True)
    (stream_root / "_config.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "project_id": 1,
                "symbols": ["AAPL"],
                "market_data_type": "delayed",
                "refresh_interval_seconds": 5,
                "stale_seconds": 15,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    runner = ib_stream.IBStreamRunner(project_id=1, data_root=tmp_path, api_mode="mock")

    class DummySettings:
        api_mode = "mock"
        host = "127.0.0.1"
        port = 4001
        client_id = 1

    monkeypatch.setattr(ib_stream, "get_or_create_ib_settings", lambda session: DummySettings())
    monkeypatch.setattr(ib_stream, "SessionLocal", lambda: type("S", (), {"close": lambda self: None})())
    monkeypatch.setattr(runner, "_ensure_client", lambda settings, symbols: None)

    def _raise_snapshot_error(symbols):
        raise RuntimeError("ib_connect_timeout")

    monkeypatch.setattr(runner, "_refresh_snapshot_if_stale", _raise_snapshot_error)

    def _stop(*_args, **_kwargs):
        raise RuntimeError("stop")

    monkeypatch.setattr(ib_stream.time, "sleep", _stop)

    try:
        runner.run_forever()
    except RuntimeError as exc:
        assert str(exc) == "stop"

    status = ib_stream.get_stream_status(tmp_path)
    assert status["phase"] == "snapshot_error"
    assert "ib_connect_timeout" in (status.get("last_error") or "")


def test_stream_runner_records_snapshot_timeout(tmp_path, monkeypatch):
    stream_root = tmp_path / "stream"
    stream_root.mkdir(parents=True, exist_ok=True)
    (stream_root / "_config.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "project_id": 1,
                "symbols": ["AAPL"],
                "market_data_type": "delayed",
                "refresh_interval_seconds": 5,
                "stale_seconds": 15,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    runner = ib_stream.IBStreamRunner(
        project_id=1,
        data_root=tmp_path,
        api_mode="mock",
        snapshot_timeout_seconds=1,
    )

    class DummySettings:
        api_mode = "mock"
        host = "127.0.0.1"
        port = 4001
        client_id = 1

    monkeypatch.setattr(ib_stream, "get_or_create_ib_settings", lambda session: DummySettings())
    monkeypatch.setattr(ib_stream, "SessionLocal", lambda: type("S", (), {"close": lambda self: None})())
    monkeypatch.setattr(runner, "_ensure_client", lambda settings, symbols: None)

    def _raise_timeout(*_args, **_kwargs):
        raise TimeoutError("boom")

    monkeypatch.setattr(ib_stream, "_fetch_snapshots_with_timeout", _raise_timeout)

    def _stop(*_args, **_kwargs):
        raise RuntimeError("stop")

    monkeypatch.setattr(ib_stream.time, "sleep", _stop)

    try:
        runner.run_forever()
    except RuntimeError as exc:
        assert str(exc) == "stop"

    status = ib_stream.get_stream_status(tmp_path)
    assert status["phase"] == "snapshot_error"
    assert "snapshot_timeout" in (status.get("last_error") or "")
