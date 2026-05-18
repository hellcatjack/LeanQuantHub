from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.generate_options_income_report import evaluate_candidate


def test_evaluate_candidate_passes_when_return_improves_and_risk_stays_bounded() -> None:
    result = evaluate_candidate(
        baseline={
            "cagr": 0.08,
            "sharpe": 0.62,
            "max_drawdown": 0.128,
            "ulcer_index": 5.0,
            "recovery_days": 120,
        },
        candidate={
            "cagr": 0.086,
            "sharpe": 0.69,
            "max_drawdown": 0.138,
            "ulcer_index": 5.3,
            "recovery_days": 132,
        },
    )
    assert result["passed"] is True


def test_evaluate_candidate_fails_when_drawdown_gate_breaks() -> None:
    result = evaluate_candidate(
        baseline={
            "cagr": 0.08,
            "sharpe": 0.62,
            "max_drawdown": 0.128,
            "ulcer_index": 5.0,
            "recovery_days": 120,
        },
        candidate={
            "cagr": 0.095,
            "sharpe": 0.71,
            "max_drawdown": 0.150,
            "ulcer_index": 5.4,
            "recovery_days": 128,
        },
    )
    assert result["passed"] is False
    assert "max_drawdown" in result["reasons"]
