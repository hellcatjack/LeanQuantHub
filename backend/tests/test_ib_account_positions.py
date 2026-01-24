from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_positions_merge_snapshot():
    from app.services.ib_account import _merge_position_prices

    positions = [{"symbol": "AAPL", "position": 1.0, "avg_cost": 100.0}]
    snapshots = {"AAPL": {"price": 120.0}}
    merged = _merge_position_prices(positions, snapshots)
    assert merged[0]["market_price"] == 120.0
