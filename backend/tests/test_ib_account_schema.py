from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas import IBAccountSummaryOut


def test_ib_account_summary_schema_accepts_optional_fields():
    payload = {
        "refreshed_at": "2026-01-24T00:00:00Z",
        "source": "cache",
        "stale": False,
        "items": {"NetLiquidation": 123.0},
        "full": False,
    }
    obj = IBAccountSummaryOut(**payload)
    assert obj.items["NetLiquidation"] == 123.0
