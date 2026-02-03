from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import universe_exclude


def test_exclude_service_create_and_upsert(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir()

    universe_exclude.ensure_exclude_file(data_root)
    items = universe_exclude.load_exclude_items(data_root, include_disabled=True)
    symbols = {item["symbol"] for item in items}
    assert {"WY", "XOM", "YUM"}.issubset(symbols)

    universe_exclude.upsert_exclude_item(
        data_root, symbol="ABCD", reason="test", source="manual/ui", enabled=True
    )
    active = universe_exclude.load_exclude_symbols(data_root)
    assert "ABCD" in active

    universe_exclude.set_exclude_enabled(data_root, symbol="ABCD", enabled=False)
    active = universe_exclude.load_exclude_symbols(data_root)
    assert "ABCD" not in active
