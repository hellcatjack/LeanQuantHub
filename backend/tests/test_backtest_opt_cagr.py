from pathlib import Path
import sys
import pytest

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


def test_parse_summary_and_dd_guard(tmp_path):
    summary_path = tmp_path / "-summary.json"
    summary_path.write_text('{"statistics": {"Compounding Annual Return": "12.3%", "Drawdown": "14.9%"}}')
    from app.services.backtest_opt_cagr import parse_summary, is_acceptable

    stats = parse_summary(summary_path)
    assert stats["cagr"] == pytest.approx(0.123)
    assert stats["dd"] == pytest.approx(0.149)
    assert is_acceptable(stats, max_dd=0.15) is True
