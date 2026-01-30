from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_execution


def test_ingest_events_updates_orders(monkeypatch, tmp_path):
    events_path = tmp_path / "events.json"
    events_path.write_text('[{"order_id": 1, "status": "FILLED", "fill_price": 100}]')
    calls = {"updated": False}

    def _fake_apply(*args, **kwargs):
        calls["updated"] = True

    monkeypatch.setattr(lean_execution, "apply_execution_events", _fake_apply, raising=False)

    lean_execution.ingest_execution_events(str(events_path))
    assert calls["updated"]


def test_ingest_events_jsonl_calls_apply(monkeypatch, tmp_path):
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        '{"tag": "oi_1", "status": "Submitted"}\n'
        '{"tag": "oi_1", "status": "Filled", "filled": 1, "fill_price": 10}\n'
    )
    calls = {"payload": None}

    def _fake_apply(events):
        calls["payload"] = events

    monkeypatch.setattr(lean_execution, "apply_execution_events", _fake_apply, raising=False)

    lean_execution.ingest_execution_events(str(events_path))
    assert calls["payload"] is not None
    assert len(calls["payload"]) == 2
