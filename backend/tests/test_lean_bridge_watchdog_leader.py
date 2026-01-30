from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_bridge_watchdog


def test_ensure_lean_bridge_live_uses_leader(monkeypatch, tmp_path):
    called = {"value": False}

    def _ensure(session, *, mode: str, force: bool = False):
        called["value"] = True
        return {"status": "ok", "last_heartbeat": datetime.now(timezone.utc).isoformat()}

    monkeypatch.setattr(lean_bridge_watchdog, "ensure_lean_bridge_leader", _ensure)
    monkeypatch.setattr(lean_bridge_watchdog, "resolve_bridge_root", lambda: tmp_path)
    monkeypatch.setattr(
        lean_bridge_watchdog,
        "read_bridge_status",
        lambda _root: {"status": "ok", "stale": True, "last_heartbeat": None},
    )

    out = lean_bridge_watchdog.ensure_lean_bridge_live(None, mode="paper", force=False)

    assert called["value"] is True
    assert out.get("status") == "ok"
