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


def test_ingest_events_jsonl_single_object_calls_apply(monkeypatch, tmp_path):
    # A single-line jsonl file is valid JSON (dict) and must still be treated as one event.
    events_path = tmp_path / "events.jsonl"
    events_path.write_text('{"tag": "direct:1", "status": "Submitted"}\n')
    calls = {"payload": None}

    def _fake_apply(events):
        calls["payload"] = events

    monkeypatch.setattr(lean_execution, "apply_execution_events", _fake_apply, raising=False)

    lean_execution.ingest_execution_events(str(events_path))
    assert calls["payload"] is not None
    assert len(calls["payload"]) == 1
    assert calls["payload"][0]["tag"] == "direct:1"


def test_ingest_events_jsonl_initial_replay_uses_tail_guardrail(monkeypatch, tmp_path):
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        "".join(f'{{"tag":"oi_{idx}","status":"Submitted"}}\n' for idx in range(1, 80)),
        encoding="utf-8",
    )
    calls = {"payload": None}

    def _fake_apply(events):
        calls["payload"] = events

    monkeypatch.setattr(lean_execution, "apply_execution_events", _fake_apply, raising=False)
    monkeypatch.setattr(lean_execution, "_JSONL_INITIAL_REPLAY_MAX_BYTES", 256, raising=False)
    lean_execution._JSONL_INGEST_STATE.clear()

    lean_execution.ingest_execution_events(str(events_path))

    payload = calls["payload"]
    assert payload is not None
    assert payload
    tags = [str(item.get("tag")) for item in payload if isinstance(item, dict)]
    assert "oi_1" not in tags
    assert "oi_79" in tags
