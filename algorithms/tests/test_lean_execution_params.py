from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "AlgorithmImports" not in sys.modules:
    stub = types.ModuleType("AlgorithmImports")

    class FeeModel:
        pass

    class EquityFillModel:
        pass

    class QCAlgorithm:
        pass

    class Security:
        pass

    class OrderFeeParameters:
        pass

    class OrderFee:
        def __init__(self, *args, **kwargs):
            pass

    class CashAmount:
        def __init__(self, *args, **kwargs):
            pass

    class MarketOrder:
        pass

    class MarketOnOpenOrder:
        pass

    class MarketOnCloseOrder:
        pass

    class Order:
        pass

    class OrderEvent:
        pass

    class NullSlippageModel:
        pass

    class RollingWindow:
        def __init__(self, *args, **kwargs):
            pass

    class Resolution:
        DAILY = "DAILY"

    class OrderDirection:
        BUY = 1
        SELL = -1

    class OrderStatus:
        FILLED = "FILLED"

    stub.FeeModel = FeeModel
    stub.EquityFillModel = EquityFillModel
    stub.QCAlgorithm = QCAlgorithm
    stub.Security = Security
    stub.OrderFeeParameters = OrderFeeParameters
    stub.OrderFee = OrderFee
    stub.CashAmount = CashAmount
    stub.MarketOrder = MarketOrder
    stub.MarketOnOpenOrder = MarketOnOpenOrder
    stub.MarketOnCloseOrder = MarketOnCloseOrder
    stub.Order = Order
    stub.OrderEvent = OrderEvent
    stub.NullSlippageModel = NullSlippageModel
    stub.RollingWindow = RollingWindow
    stub.Resolution = Resolution
    stub.OrderDirection = OrderDirection
    stub.OrderStatus = OrderStatus
    stub.__all__ = [
        "FeeModel",
        "EquityFillModel",
        "QCAlgorithm",
        "Security",
        "OrderFeeParameters",
        "OrderFee",
        "CashAmount",
        "MarketOrder",
        "MarketOnOpenOrder",
        "MarketOnCloseOrder",
        "Order",
        "OrderEvent",
        "NullSlippageModel",
        "RollingWindow",
        "Resolution",
        "OrderDirection",
        "OrderStatus",
    ]
    sys.modules["AlgorithmImports"] = stub

from algorithms.lean_trend_rotation import _apply_execution_constraints


def test_apply_execution_constraints_min_qty():
    qty = _apply_execution_constraints(raw_qty=0.2, lot_size=1, min_qty=1)
    assert qty == 1
