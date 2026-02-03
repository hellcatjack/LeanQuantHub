from contextlib import contextmanager
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.routes import trade as trade_routes


def test_auto_recovery_route_returns_counts(monkeypatch):
    @contextmanager
    def _get_session():
        yield None

    monkeypatch.setattr(trade_routes, "get_session", _get_session)
    monkeypatch.setattr(
        trade_routes,
        "run_auto_recovery",
        lambda *_args, **_kwargs: {"scanned": 1, "cancelled": 1, "replaced": 0, "skipped": 0, "failed": 0},
        raising=False,
    )

    out = trade_routes.auto_recover_trade_orders()

    assert out.cancelled == 1
