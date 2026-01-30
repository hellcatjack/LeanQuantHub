from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.trade_executor import determine_run_status


def test_determine_run_status_done_when_all_filled():
    status, summary = determine_run_status(["FILLED", "FILLED"])
    assert status == "done"
    assert summary["filled"] == 2


def test_determine_run_status_partial_when_mixed_terminal():
    status, summary = determine_run_status(["FILLED", "REJECTED"])
    assert status == "partial"
    assert summary["rejected"] == 1


def test_determine_run_status_failed_when_no_fills():
    status, summary = determine_run_status(["REJECTED", "CANCELED"])
    assert status == "failed"
    assert summary["filled"] == 0


def test_determine_run_status_pending_when_non_terminal():
    status, summary = determine_run_status(["NEW", "FILLED"])
    assert status is None
    assert summary["total"] == 2
