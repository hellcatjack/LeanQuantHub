from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.decision_snapshot import _apply_algorithm_params


def test_apply_algorithm_params_cold_start_turnover():
    weights_cfg = {}
    algo_params = {"max_turnover_week": 0.1, "cold_start_turnover": 0.3}
    result = _apply_algorithm_params(weights_cfg, algo_params)
    assert result["turnover_limit"] == 0.1
    assert result["cold_start_turnover"] == 0.3
