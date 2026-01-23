from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import trade_monitor


def test_trade_overview_shape():
    payload = trade_monitor.build_trade_overview(None, project_id=1, mode="paper")
    assert "positions" in payload
