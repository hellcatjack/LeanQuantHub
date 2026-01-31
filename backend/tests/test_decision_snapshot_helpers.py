from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import decision_snapshot


def test_normalize_snapshot_row_applies_fallback_date():
    row = {"snapshot_date": "", "rebalance_date": ""}
    normalized = decision_snapshot._normalize_snapshot_row(row, "2026-01-23")
    assert normalized["snapshot_date"] == "2026-01-23"
    assert normalized["rebalance_date"] == "2026-01-23"


def test_normalize_snapshot_row_preserves_existing_date():
    row = {"snapshot_date": "2026-01-09", "rebalance_date": "2026-01-10"}
    normalized = decision_snapshot._normalize_snapshot_row(row, "2026-01-23")
    assert normalized["snapshot_date"] == "2026-01-09"
    assert normalized["rebalance_date"] == "2026-01-10"
