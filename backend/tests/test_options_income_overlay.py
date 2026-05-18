from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from algorithms.options_income_overlay import apply_income_sleeve


def test_apply_income_sleeve_idle_replacement() -> None:
    weights = {"AMD": 0.30, "NVDA": 0.20, "SGOV": 0.50}
    result = apply_income_sleeve(
        weights=weights,
        idle_symbol="SGOV",
        income_symbol="JEPI",
        sleeve_weight=0.20,
        mode="idle_replacement",
    )
    assert result["JEPI"] == 0.20
    assert result["SGOV"] == 0.30
    assert result["AMD"] == 0.30
    assert result["NVDA"] == 0.20


def test_apply_income_sleeve_defensive_replacement() -> None:
    weights = {"AMD": 0.30, "NVDA": 0.20, "SGOV": 0.50}
    result = apply_income_sleeve(
        weights=weights,
        idle_symbol="SGOV",
        income_symbol="DIVO",
        sleeve_weight=0.30,
        mode="defensive_replacement",
    )
    assert result["DIVO"] == 0.30
    assert result["SGOV"] == 0.20
