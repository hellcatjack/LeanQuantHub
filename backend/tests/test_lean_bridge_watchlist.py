from pathlib import Path

from app.services.lean_bridge_watchlist import write_watchlist


def test_write_watchlist_dedup_and_sort(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.json"
    payload = write_watchlist(path, [" aapl", "MSFT", "AAPL", ""], meta={"source": "test"})
    assert payload["symbols"] == ["AAPL", "MSFT"]
    assert path.exists()
