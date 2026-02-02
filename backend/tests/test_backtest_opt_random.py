from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.backtest_opt_random import generate_candidates


def test_generate_candidates_respects_constraints():
    base = {
        "top_n": 30,
        "retain_top_n": 10,
        "max_weight": 0.033,
        "max_exposure": 0.45,
        "vol_target": 0.055,
        "max_drawdown": 0.15,
        "max_turnover_week": 0.08,
        "market_ma_window": 200,
    }
    candidates = generate_candidates(base, total=20, seed=7)
    assert len(candidates) == 20
    for item in candidates:
        assert item["retain_top_n"] <= item["top_n"]
        assert 0.01 <= item["max_weight"] <= 0.12
