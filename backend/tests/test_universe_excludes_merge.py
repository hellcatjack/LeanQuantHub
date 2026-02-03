from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import universe_exclude


def test_merge_legacy_excludes(tmp_path: Path):
    data_root = tmp_path / "data"
    (data_root / "universe").mkdir(parents=True)
    legacy = data_root / "universe" / "alpha_exclude_symbols.csv"
    legacy.write_text("symbol,reason\nABC,legacy\n", encoding="utf-8")

    universe_exclude.merge_legacy_excludes(data_root)
    symbols = universe_exclude.load_exclude_symbols(data_root)
    assert "ABC" in symbols
