from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import ib_market


class _DummySettings:
    host = "127.0.0.1"
    port = 7497
    client_id = 1
    api_mode = "ib"


def test_ib_adapter_retries_on_timeout(monkeypatch):
    calls = {"count": 0}

    class _Adapter:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("ib_connect_timeout")
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    slept = {"count": 0}

    def _sleep(_seconds):
        slept["count"] += 1

    monkeypatch.setattr(ib_market, "IBLiveAdapter", _Adapter)
    monkeypatch.setattr(ib_market, "resolve_ib_api_mode", lambda _settings: "ib")
    monkeypatch.setattr(ib_market.time, "sleep", _sleep)

    with ib_market.ib_adapter(_DummySettings()) as _api:
        assert _api is not None

    assert calls["count"] == 2
    assert slept["count"] == 1
