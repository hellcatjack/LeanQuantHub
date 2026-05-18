from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.options_income_policy import (
    DEFAULT_OPTIONS_INCOME_BENCHMARK,
    DEFAULT_OPTIONS_INCOME_DEFENSIVE_BASKET,
    DEFAULT_OPTIONS_INCOME_DEFENSIVE_SYMBOL,
    load_options_income_matrix,
    load_options_income_thresholds,
)


def test_options_income_policy_defaults_and_thresholds() -> None:
    matrix = load_options_income_matrix()
    thresholds = load_options_income_thresholds()

    assert DEFAULT_OPTIONS_INCOME_DEFENSIVE_SYMBOL == "SGOV"
    assert DEFAULT_OPTIONS_INCOME_DEFENSIVE_BASKET == ["SGOV", "VGSH"]
    assert DEFAULT_OPTIONS_INCOME_BENCHMARK == "SPY"
    assert matrix["proxy_assets"] == ["JEPI", "JEPQ", "XYLD", "QYLD", "DIVO"]
    assert thresholds["max_drawdown_delta_pp"] == 1.5
    assert thresholds["recovery_time_delta_ratio"] == 0.20
    assert thresholds["ulcer_index_delta_ratio"] == 0.10
    assert thresholds["min_cagr_delta_pp"] == 0.5
    assert thresholds["min_sharpe_delta"] == 0.05
