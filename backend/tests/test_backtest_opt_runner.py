from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

from app.services.backtest_opt_runner import (
    parse_pct,
    merge_algo_params,
    select_core_params,
)


def test_parse_pct():
    assert parse_pct("12.3%") == pytest.approx(0.123)
    assert parse_pct("0") == 0.0
    assert parse_pct(None) == 0.0


def test_merge_algo_params_prefers_base():
    base = {"top_n": 30, "max_weight": 0.033}
    defaults = {"top_n": 50, "max_drawdown": 0.15}
    merged = merge_algo_params(base, defaults)
    assert merged["top_n"] == 30
    assert merged["max_weight"] == 0.033
    assert merged["max_drawdown"] == 0.15


def test_select_core_params_coerces():
    base = {
        "max_weight": "0.033",
        "max_exposure": "0.45",
        "vol_target": 0.055,
        "max_drawdown": "0.15",
        "top_n": "30",
        "retain_top_n": "10",
        "max_turnover_week": "0.08",
        "market_ma_window": "200",
    }
    core = select_core_params(base)
    assert core["top_n"] == 30
    assert core["market_ma_window"] == 200
    assert core["max_weight"] == 0.033
