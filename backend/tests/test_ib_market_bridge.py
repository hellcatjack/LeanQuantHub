from __future__ import annotations

import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import ib_market


def test_fetch_market_snapshots_from_lean_bridge(tmp_path, monkeypatch):
    bridge_root = tmp_path / "lean_bridge"
    bridge_root.mkdir(parents=True, exist_ok=True)
    (bridge_root / "quotes.json").write_text(
        json.dumps(
            {
                "items": [
                    {"symbol": "SPY", "last": 100, "timestamp": "2026-01-16T10:00:00Z"},
                ],
                "stale": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ib_market, "_resolve_bridge_root", lambda: bridge_root, raising=False)

    items = ib_market.fetch_market_snapshots(None, symbols=["SPY", "QQQ"], store=False)

    assert len(items) == 2
    spy = next(item for item in items if item.get("symbol") == "SPY")
    qqq = next(item for item in items if item.get("symbol") == "QQQ")
    assert spy.get("error") is None
    assert spy.get("data", {}).get("last") == 100
    assert qqq.get("error") == "quote_missing"
