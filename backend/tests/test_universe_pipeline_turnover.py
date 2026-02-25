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


def test_normalize_drawdown_tier_exposures_aligns_lengths():
    tiers = up.normalize_drawdown_tier_exposures("0.05,0.10,0.15", "0.8,0.6")
    assert tiers == [(0.05, 0.8), (0.1, 0.6), (0.15, 0.6)]


def test_resolve_drawdown_exposure_cap_uses_tier_and_floor():
    cap, threshold, tier_exposure = up.resolve_drawdown_exposure_cap(
        current_drawdown=0.12,
        max_exposure=0.45,
        dynamic_exposure=True,
        drawdown_tiers=[(0.05, 0.4), (0.1, 0.2)],
        drawdown_exposure_floor=0.25,
    )
    assert cap == 0.25
    assert threshold == 0.1
    assert tier_exposure == 0.2


def test_resolve_drawdown_exposure_cap_disabled_uses_max_exposure():
    cap, threshold, tier_exposure = up.resolve_drawdown_exposure_cap(
        current_drawdown=0.2,
        max_exposure=0.45,
        dynamic_exposure=False,
        drawdown_tiers=[(0.05, 0.4), (0.1, 0.2)],
        drawdown_exposure_floor=0.1,
    )
    assert cap == 0.45
    assert threshold is None
    assert tier_exposure is None
