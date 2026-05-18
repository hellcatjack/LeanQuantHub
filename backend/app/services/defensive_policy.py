from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_DEFENSIVE_SYMBOL = "SGOV"
DEFAULT_DEFENSIVE_SYMBOLS = ("SGOV", "VGSH")
DEFAULT_DEFENSIVE_BASKET = ",".join(DEFAULT_DEFENSIVE_SYMBOLS)
DEFAULT_BENCHMARK = "SPY"

CONSERVATIVE_DEFENSIVE_SYMBOLS = ("SGOV", "VGSH", "IEF")
RESEARCH_ONLY_SYMBOLS = ("GLD", "USO", "BNO", "TLT", "QQQ", "SOXX")

REPO_ROOT = Path(__file__).resolve().parents[3]
RESEARCH_MATRIX_PATH = REPO_ROOT / "configs" / "research_defensive_matrix.json"


def get_default_defensive_policy() -> dict[str, Any]:
    return {
        "risk_off_symbol": DEFAULT_DEFENSIVE_SYMBOL,
        "risk_off_symbols": list(DEFAULT_DEFENSIVE_SYMBOLS),
        "risk_off_basket": DEFAULT_DEFENSIVE_BASKET,
        "benchmark": DEFAULT_BENCHMARK,
    }


def get_conservative_defensive_policy() -> dict[str, Any]:
    return {
        "risk_off_symbol": DEFAULT_DEFENSIVE_SYMBOL,
        "risk_off_symbols": list(CONSERVATIVE_DEFENSIVE_SYMBOLS),
        "benchmark": DEFAULT_BENCHMARK,
    }


def load_research_defensive_matrix() -> dict[str, Any]:
    return json.loads(RESEARCH_MATRIX_PATH.read_text(encoding="utf-8"))
