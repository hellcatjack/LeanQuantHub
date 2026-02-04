from datetime import datetime, timedelta
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.trade_run_progress import is_trade_run_stalled


class DummyRun:
    def __init__(
        self,
        *,
        status: str = "running",
        last_progress_at: datetime | None = None,
        started_at: datetime | None = None,
        updated_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.status = status
        self.last_progress_at = last_progress_at
        self.started_at = started_at
        self.updated_at = updated_at
        self.created_at = created_at


def test_trade_run_stalled_true():
    now = datetime.utcnow()
    run = DummyRun(last_progress_at=now - timedelta(minutes=16))
    assert is_trade_run_stalled(run, now, window_minutes=15, trading_open=True) is True


def test_trade_run_stalled_false_when_recent():
    now = datetime.utcnow()
    run = DummyRun(last_progress_at=now - timedelta(minutes=5))
    assert is_trade_run_stalled(run, now, window_minutes=15, trading_open=True) is False


def test_trade_run_stalled_false_when_not_running():
    now = datetime.utcnow()
    run = DummyRun(status="failed", last_progress_at=now - timedelta(minutes=30))
    assert is_trade_run_stalled(run, now, window_minutes=15, trading_open=True) is False


def test_trade_run_stalled_false_when_market_closed():
    now = datetime.utcnow()
    run = DummyRun(last_progress_at=now - timedelta(minutes=30))
    assert is_trade_run_stalled(run, now, window_minutes=15, trading_open=False) is False


def test_trade_run_stalled_uses_started_at_when_no_progress():
    now = datetime.utcnow()
    run = DummyRun(last_progress_at=None, started_at=now - timedelta(minutes=20))
    assert is_trade_run_stalled(run, now, window_minutes=15, trading_open=True) is True
