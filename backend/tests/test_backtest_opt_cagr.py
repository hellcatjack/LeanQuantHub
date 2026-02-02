from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.backtest_opt_cagr import build_grid


def test_build_grid_has_expected_candidates():
    base = {"max_exposure": 0.45, "vol_target": 0.055, "max_drawdown": 0.15}
    grid = build_grid(base)
    assert isinstance(grid, list)
    assert len(grid) >= 12
    assert all("max_exposure" in item for item in grid)
    assert all("vol_target" in item for item in grid)
