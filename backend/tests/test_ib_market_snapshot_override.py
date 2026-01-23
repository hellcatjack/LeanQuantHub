from pathlib import Path
from types import SimpleNamespace
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import ib_market


class _DummyQuery:
    def filter(self, *args, **kwargs):
        return self

    def one_or_none(self):
        return None


class _DummySession:
    def query(self, *args, **kwargs):
        return _DummyQuery()


def test_fetch_market_snapshots_uses_override(monkeypatch):
    called = {"value": None}

    def _market_data_type_id(value):
        called["value"] = value
        return 3

    monkeypatch.setattr(ib_market, "_market_data_type_id", _market_data_type_id)
    monkeypatch.setattr(
        ib_market,
        "ensure_ib_client_id",
        lambda _session, **_kwargs: SimpleNamespace(
            market_data_type="realtime",
            use_regulatory_snapshot=False,
            api_mode="mock",
        ),
    )

    session = _DummySession()
    ib_market.fetch_market_snapshots(session, symbols=["SPY"], store=False, market_data_type="delayed")
    assert called["value"] == "delayed"
