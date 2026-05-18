from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.covered_call_planner import pick_covered_call_candidate


def _expiry(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


def test_pick_covered_call_candidate_prefers_otm_tighter_spread() -> None:
    candidates = [
        {
            "expiry": _expiry(30),
            "strike": 220.0,
            "underlying_price": 225.0,
            "right": "C",
            "bid": 2.0,
            "ask": 3.0,
        },
        {
            "expiry": _expiry(30),
            "strike": 230.0,
            "underlying_price": 225.0,
            "right": "C",
            "bid": 1.2,
            "ask": 1.3,
        },
    ]

    picked = pick_covered_call_candidate(
        candidates,
        dte_min=21,
        dte_max=45,
        max_spread_ratio=0.15,
    )

    assert picked is not None
    assert picked["strike"] == 230.0


def test_pick_covered_call_candidate_filters_wide_spread_and_non_call() -> None:
    candidates = [
        {
            "expiry": _expiry(30),
            "strike": 230.0,
            "underlying_price": 225.0,
            "right": "P",
            "bid": 1.2,
            "ask": 1.3,
        },
        {
            "expiry": _expiry(30),
            "strike": 230.0,
            "underlying_price": 225.0,
            "right": "C",
            "bid": 1.0,
            "ask": 2.0,
        },
    ]

    picked = pick_covered_call_candidate(
        candidates,
        dte_min=21,
        dte_max=45,
        max_spread_ratio=0.15,
    )

    assert picked is None



def test_pick_covered_call_candidate_rejects_missing_underlying_price():
    choice = pick_covered_call_candidate(
        [
            {
                "symbol": "AAPL",
                "expiry": _expiry(30),
                "strike": 230.0,
                "right": "C",
                "bid": 1.2,
                "ask": 1.3,
                "underlying_price": 0.0,
            }
        ],
        dte_min=21,
        dte_max=45,
        max_spread_ratio=0.15,
    )
    assert choice is None



def test_pick_covered_call_candidate_enriches_metrics_and_tags():
    picked = pick_covered_call_candidate(
        [
            {
                "symbol": "AAPL",
                "expiry": _expiry(24),
                "strike": 226.0,
                "underlying_price": 225.0,
                "right": "C",
                "bid": 1.0,
                "ask": 1.14,
            }
        ],
        dte_min=21,
        dte_max=45,
        max_spread_ratio=0.15,
    )
    assert picked is not None
    assert picked["dte"] >= 21
    assert picked["spread_ratio"] > 0
    assert picked["moneyness_pct"] > 0
    assert "tight_otm_buffer" in picked["risk_tags"]
    assert "spread_near_limit" in picked["risk_tags"]
