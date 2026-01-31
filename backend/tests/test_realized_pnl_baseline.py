from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.realized_pnl_baseline import ensure_positions_baseline


def test_baseline_created_from_positions(tmp_path):
    root = tmp_path / "lean_bridge"
    root.mkdir(parents=True)
    payload = {
        "source_detail": "ib_holdings",
        "stale": False,
        "updated_at": "2026-01-30T00:00:00Z",
        "items": [{"symbol": "AAPL", "position": 10, "avg_cost": 100.0}],
    }
    baseline = ensure_positions_baseline(root, payload)
    assert baseline["items"][0]["symbol"] == "AAPL"
    assert (root / "positions_baseline.json").exists()
