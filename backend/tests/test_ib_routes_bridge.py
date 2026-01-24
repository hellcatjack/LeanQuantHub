from pathlib import Path
import sys
import json

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import ib_account


def test_get_account_summary_reads_bridge_cache(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache"
    cache_root.mkdir(parents=True)
    (cache_root / "account_summary.json").write_text(json.dumps({"NetLiquidation": 123}))
    monkeypatch.setattr(ib_account, "CACHE_ROOT", cache_root, raising=False)

    payload = ib_account.get_account_summary(mode="paper", full=False)
    assert payload.get("NetLiquidation") == 123
