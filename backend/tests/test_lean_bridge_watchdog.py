from pathlib import Path

from app.services import lean_bridge_watchdog as w


def test_refresh_state_roundtrip(tmp_path: Path):
    root = tmp_path / "lean_bridge"
    root.mkdir()
    w.write_refresh_state(root, result="success", reason="manual", message="ok")
    state = w.read_refresh_state(root)
    assert state["last_refresh_result"] == "success"
    assert state["last_refresh_reason"] == "manual"
    assert state["last_refresh_message"] == "ok"
    assert "last_refresh_at" in state


def test_build_bridge_status_contains_refresh_state(tmp_path: Path):
    root = tmp_path / "lean_bridge"
    root.mkdir()
    w.write_refresh_state(root, result="skipped", reason="rate_limited", message=None)
    status = w.build_bridge_status(root)
    assert status["last_refresh_result"] == "skipped"
    assert status["last_refresh_reason"] == "rate_limited"
