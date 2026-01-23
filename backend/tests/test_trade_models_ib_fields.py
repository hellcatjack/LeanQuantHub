from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import TradeOrder, TradeFill


def test_trade_models_have_ib_fields():
    assert hasattr(TradeOrder, "ib_order_id")
    assert hasattr(TradeOrder, "ib_perm_id")
    assert hasattr(TradeFill, "exec_id")
