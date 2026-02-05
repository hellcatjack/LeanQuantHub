from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.backtest_opt_train120 import build_grid, build_perturbations


def test_grid_has_expected_size_and_values() -> None:
    grid = build_grid()
    assert len(grid) == 18
    assert {item["max_exposure"] for item in grid} == {0.60, 0.70, 0.80}
    assert {item["vol_target"] for item in grid} == {0.045, 0.050, 0.055}
    assert {item["max_weight"] for item in grid} == {0.030, 0.040}


def test_perturbations_are_unique_and_within_bounds() -> None:
    grid = build_grid()
    perturb = build_perturbations(
        base={"max_exposure": 0.70, "vol_target": 0.050, "max_weight": 0.035}
    )
    assert len(perturb) == 12
    assert len({tuple(sorted(p.items())) for p in perturb}) == 12
    assert not set(tuple(sorted(p.items())) for p in perturb).intersection(
        set(tuple(sorted(g.items())) for g in grid)
    )
    for item in perturb:
        assert 0.65 <= item["max_exposure"] <= 0.75
        assert 0.045 <= item["vol_target"] <= 0.055
        assert 0.030 <= item["max_weight"] <= 0.040
