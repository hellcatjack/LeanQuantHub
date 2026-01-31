from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas import TradeFillDetailOut


def test_fill_detail_schema_includes_realized_fields():
    payload = {
        "id": 1,
        "order_id": 1,
        "symbol": "AAPL",
        "side": "SELL",
        "exec_id": "E1",
        "fill_quantity": 1,
        "fill_price": 100.0,
        "commission": 1.0,
        "realized_pnl": 5.0,
    }
    model = TradeFillDetailOut(**payload)
    assert model.symbol == "AAPL"
    assert model.side == "SELL"
    assert model.realized_pnl == 5.0
    assert model.commission == 1.0
