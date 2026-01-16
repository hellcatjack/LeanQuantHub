import json
from pathlib import Path
from types import SimpleNamespace

import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.services import ib_market


class _DummyQuery:
    def filter(self, *args, **kwargs):
        return self

    def one_or_none(self):
        return None


class _DummySession:
    def query(self, *args, **kwargs):
        return _DummyQuery()


def test_mock_snapshot_injects_source(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_root", str(tmp_path))

    mock_root = tmp_path / "ib" / "mock"
    mock_root.mkdir(parents=True, exist_ok=True)
    (mock_root / "snapshots.json").write_text(
        json.dumps({"SPY": {"last": 123.0, "close": 123.0}}),
        encoding="utf-8",
    )

    dummy_settings = SimpleNamespace(
        market_data_type="realtime",
        use_regulatory_snapshot=False,
        api_mode="mock",
    )
    monkeypatch.setattr(ib_market, "get_or_create_ib_settings", lambda _session: dummy_settings)

    session = _DummySession()
    result = ib_market.fetch_market_snapshots(session, symbols=["SPY"], store=False)
    assert result
    payload = result[0]["data"]
    assert payload is not None
    assert payload.get("source") == "mock"
