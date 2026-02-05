from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.backtest_opt_train120_v2 import build_grid, build_contrast


def test_v2_grid_size_and_bounds() -> None:
    grid = build_grid()
    assert len(grid) == 24
    assert {g["max_exposure"] for g in grid} == {0.30, 0.32, 0.34, 0.36}
    assert {g["vol_target"] for g in grid} == {0.040, 0.0425, 0.045}
    assert {g["max_weight"] for g in grid} == {0.022, 0.026}


def test_v2_contrast_group() -> None:
    contrast = build_contrast()
    assert len(contrast) == 6
    for item in contrast:
        assert item["drawdown_tiers"] == "0.05,0.10,0.13"
        assert item["drawdown_exposures"] == "0.50,0.35,0.25"
