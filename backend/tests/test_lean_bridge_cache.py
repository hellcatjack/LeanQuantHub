from pathlib import Path
import sys
import json

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_bridge


def test_write_bridge_cache(tmp_path, monkeypatch):
    bridge_root = tmp_path / "lean_bridge"
    bridge_root.mkdir()
    (bridge_root / "account_summary.json").write_text(json.dumps({"NetLiquidation": 100}))
    (bridge_root / "positions.json").write_text("[]")
    (bridge_root / "quotes.json").write_text("[]")

    cache_root = tmp_path / "cache"
    monkeypatch.setattr(lean_bridge, "BRIDGE_ROOT", bridge_root, raising=False)
    monkeypatch.setattr(lean_bridge, "CACHE_ROOT", cache_root, raising=False)

    lean_bridge.refresh_bridge_cache()

    assert (cache_root / "account_summary.json").exists()
    payload = json.loads((cache_root / "account_summary.json").read_text())
    assert payload.get("NetLiquidation") == 100
