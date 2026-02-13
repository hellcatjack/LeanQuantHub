from pathlib import Path
import sys
import json

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.lean_bridge_commands import write_submit_order_command


def test_write_submit_order_command_writes_payload(tmp_path):
    ref = write_submit_order_command(
        tmp_path,
        symbol="AAPL",
        quantity=2,
        tag="oi_1_1",
        order_type="ADAPTIVE_LMT",
        order_id=101,
        outside_rth=False,
        adaptive_priority="Normal",
    )

    payload = json.loads(Path(ref.command_path).read_text(encoding="utf-8"))
    assert payload["type"] == "submit_order"
    assert payload["symbol"] == "AAPL"
    assert float(payload["quantity"]) == 2.0
    assert payload["tag"] == "oi_1_1"
    assert payload["order_type"] == "ADAPTIVE_LMT"
    assert payload["order_id"] == 101
    assert payload["outside_rth"] is False
