from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.options_eligibility import evaluate_covered_call_eligibility


def test_covered_call_eligibility_rejects_small_position() -> None:
    result = evaluate_covered_call_eligibility(
        symbol="NVDA",
        shares=75,
        has_open_orders=False,
        has_option_position=False,
        runtime_state="healthy",
        mode="paper",
    )

    assert result["eligible"] is False
    assert result["reason"] == "shares_below_100"


def test_covered_call_eligibility_accepts_round_lot_position() -> None:
    result = evaluate_covered_call_eligibility(
        symbol="AAPL",
        shares=250,
        has_open_orders=False,
        has_option_position=False,
        runtime_state="healthy",
        mode="paper",
    )

    assert result["eligible"] is True
    assert result["coverable_contracts"] == 2
