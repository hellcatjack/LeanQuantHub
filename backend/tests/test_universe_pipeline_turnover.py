from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import universe_pipeline as up


def test_resolve_turnover_limit_cold_start():
    effective, cold_start = up.resolve_turnover_limit(0.1, 0.3, prev_weight_sum=0.0)
    assert cold_start is True
    assert effective == 0.3


def test_resolve_turnover_limit_non_cold_start():
    effective, cold_start = up.resolve_turnover_limit(0.1, 0.3, prev_weight_sum=0.2)
    assert cold_start is False
    assert effective == 0.1


def test_resolve_turnover_limit_fallback():
    effective, cold_start = up.resolve_turnover_limit(0.1, None, prev_weight_sum=0.0)
    assert cold_start is True
    assert effective == 0.1
