from pathlib import Path
import json
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.lean_bridge_commands import write_submit_order_command


def test_write_submit_order_command_keeps_stock_payload_shape(tmp_path: Path) -> None:
    ref = write_submit_order_command(
        tmp_path,
        symbol="AAPL",
        quantity=10,
        tag="stock-order-1",
        order_type="MKT",
    )

    payload = json.loads(Path(ref.command_path).read_text(encoding="utf-8"))

    assert payload["type"] == "submit_order"
    assert payload["symbol"] == "AAPL"
    assert payload["quantity"] == 10.0
    assert payload["order_type"] == "MKT"
    assert "sec_type" not in payload
    assert "expiry" not in payload
    assert "strike" not in payload


def test_write_submit_order_command_writes_option_contract_fields(tmp_path: Path) -> None:
    ref = write_submit_order_command(
        tmp_path,
        symbol="AAPL",
        underlying_symbol="AAPL",
        sec_type="OPT",
        expiry="2026-05-15",
        strike=210.0,
        right="C",
        multiplier=100,
        quantity=-1,
        tag="covered_call:review-1",
        order_type="LMT",
        limit_price=1.25,
    )

    payload = json.loads(Path(ref.command_path).read_text(encoding="utf-8"))

    assert payload["sec_type"] == "OPT"
    assert payload["underlying_symbol"] == "AAPL"
    assert payload["expiry"] == "2026-05-15"
    assert payload["strike"] == 210.0
    assert payload["right"] == "C"
    assert payload["multiplier"] == 100
    assert payload["quantity"] == -1.0
    assert payload["order_type"] == "LMT"
    assert payload["limit_price"] == 1.25


def test_write_submit_order_command_rejects_missing_option_contract_fields(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="expiry_required"):
        write_submit_order_command(
            tmp_path,
            symbol="AAPL",
            underlying_symbol="AAPL",
            sec_type="OPT",
            strike=210.0,
            right="C",
            multiplier=100,
            quantity=-1,
            tag="covered_call:review-1",
            order_type="LMT",
            limit_price=1.25,
        )
