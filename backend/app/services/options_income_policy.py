from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_OPTIONS_INCOME_DEFENSIVE_SYMBOL = "SGOV"
DEFAULT_OPTIONS_INCOME_DEFENSIVE_BASKET = ["SGOV", "VGSH"]
DEFAULT_OPTIONS_INCOME_BENCHMARK = "SPY"

REPO_ROOT = Path(__file__).resolve().parents[3]
OPTIONS_INCOME_MATRIX_PATH = REPO_ROOT / "configs" / "research_options_income_matrix.json"


@lru_cache(maxsize=1)
def load_options_income_matrix() -> dict[str, Any]:
    return json.loads(OPTIONS_INCOME_MATRIX_PATH.read_text(encoding="utf-8"))


def load_options_income_thresholds() -> dict[str, Any]:
    payload = load_options_income_matrix()
    return dict(payload.get("thresholds") or {})
