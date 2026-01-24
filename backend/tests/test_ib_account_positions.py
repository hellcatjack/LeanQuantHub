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

def test_ib_account_summary_uses_bridge(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_account_summary",
        lambda _root: {"items": [{"name": "Net", "value": 1}], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))

    payload = ib_account_module.get_account_summary(
        session=None, mode="paper", full=False, force_refresh=False
    )
    assert payload["items"]["Net"] == 1
    assert payload["stale"] is False


def test_ib_account_positions_uses_bridge(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_positions",
        lambda _root: {"items": [{"symbol": "AAA", "position": 2}], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))

    payload = ib_account_module.get_account_positions(
        session=None, mode="paper", force_refresh=False
    )
    assert payload["items"][0]["symbol"] == "AAA"
    assert payload["stale"] is False
