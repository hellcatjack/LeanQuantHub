from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.ib_options_market import normalize_option_contract_row


def test_normalize_option_contract_row_keeps_call_contract_fields() -> None:
    row = {
        "symbol": "AAPL",
        "expiry": "20260515",
        "strike": 230,
        "right": "C",
        "bid": 1.2,
        "ask": 1.4,
    }

    item = normalize_option_contract_row(row)

    assert item["symbol"] == "AAPL"
    assert item["expiry"] == "2026-05-15"
    assert item["right"] == "C"
    assert item["bid"] == 1.2
    assert item["ask"] == 1.4
