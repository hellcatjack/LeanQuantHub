from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


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
        lambda _root: {
            "items": [{"symbol": "AAA", "quantity": 2, "market_value": 10}],
            "stale": False,
            "source_detail": "ib_holdings",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))

    payload = ib_account_module.get_account_positions(
        session=None, mode="paper", force_refresh=False
    )
    assert payload["items"][0]["symbol"] == "AAA"
    assert payload["items"][0]["position"] == 2
    assert payload["items"][0]["market_price"] == 5
    assert payload["stale"] is False


def test_ib_account_positions_fill_from_quotes(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_positions",
        lambda _root: {
            "items": [
                {
                    "symbol": "AAA",
                    "quantity": 2,
                    "avg_cost": 10,
                    "market_value": 0,
                    "unrealized_pnl": 0,
                }
            ],
            "stale": False,
            "source_detail": "ib_holdings",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [{"symbol": "AAA", "last": 12.5}], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))

    payload = ib_account_module.get_account_positions(
        session=None, mode="paper", force_refresh=False
    )
    row = payload["items"][0]
    assert row["market_price"] == 12.5
    assert row["market_value"] == 25.0
    assert row["unrealized_pnl"] == 5.0


def test_ib_account_positions_rejects_non_ib_holdings(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_positions",
        lambda _root: {
            "items": [{"symbol": "AAA", "quantity": 2, "market_value": 10}],
            "stale": False,
            "source_detail": "algorithm_holdings",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))

    payload = ib_account_module.get_account_positions(
        session=None, mode="paper", force_refresh=False
    )
    assert payload["items"] == []
    assert payload["stale"] is True
