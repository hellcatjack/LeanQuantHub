from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.trade_executor import _should_skip_order_build


def test_should_skip_order_build_for_lean():
    assert _should_skip_order_build("lean") is True
    assert _should_skip_order_build("non_lean") is False
