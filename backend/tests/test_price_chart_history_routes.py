from pathlib import Path
import sys
from contextlib import contextmanager

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.routes import brokerage as brokerage_routes
from app import schemas


def test_price_chart_schema_accepts_unified_payload():
    payload = schemas.PriceChartOut(
        symbol="AAPL",
        interval="1D",
        source="ib",
        fallback_used=False,
        stale=False,
        bars=[
            schemas.PriceChartBarOut(
                time=1773187200,
                open=188.92,
                high=192.64,
                low=187.88,
                close=191.36,
                volume=58200000,
            )
        ],
        markers=[
            schemas.PriceChartMarkerOut(
                time=1773187200,
                position="belowBar",
                shape="arrowUp",
                color="#10b981",
                text="BUY",
            )
        ],
        meta=schemas.PriceChartMetaOut(
            price_precision=2,
            currency="USD",
            range_label="6M",
            last_bar_at="2026-03-10T20:00:00Z",
        ),
        error=None,
    )

    assert payload.symbol == "AAPL"
    assert payload.interval == "1D"
    assert payload.bars[0].close == 191.36
    assert payload.markers[0].text == "BUY"


def test_history_chart_response_shape(monkeypatch):
    @contextmanager
    def _get_session():
        yield object()

    monkeypatch.setattr(brokerage_routes, "get_session", _get_session)
    monkeypatch.setattr(
        brokerage_routes,
        "build_price_chart_history",
        lambda **_kwargs: {
            "symbol": "AAPL",
            "interval": "1D",
            "source": "ib",
            "fallback_used": False,
            "stale": False,
            "bars": [],
            "markers": [],
            "meta": {
                "price_precision": 2,
                "currency": "USD",
                "range_label": "6M",
                "last_bar_at": "2026-03-10T20:00:00Z",
            },
            "error": None,
        },
        raising=False,
    )
    payload = brokerage_routes.get_price_chart_history(symbol="AAPL", interval="1D")

    assert payload.symbol == "AAPL"
    assert payload.interval == "1D"
    assert isinstance(payload.bars, list)
    assert isinstance(payload.markers, list)


def test_daily_chart_route_uses_local_fallback_when_ib_fails(monkeypatch):
    @contextmanager
    def _get_session():
        yield object()

    monkeypatch.setattr(brokerage_routes, "get_session", _get_session)
    monkeypatch.setattr(
        brokerage_routes,
        "build_price_chart_history",
        lambda **_kwargs: {
            "symbol": "AAPL",
            "interval": "1D",
            "source": "local",
            "fallback_used": True,
            "stale": False,
            "bars": [
                {
                    "time": 1773187200,
                    "open": 188.92,
                    "high": 192.64,
                    "low": 187.88,
                    "close": 191.36,
                    "volume": 58200000,
                }
            ],
            "markers": [],
            "meta": {
                "price_precision": 2,
                "currency": "USD",
                "range_label": "6M",
                "last_bar_at": "2026-03-10T20:00:00Z",
            },
            "error": None,
        },
        raising=False,
    )
    payload = brokerage_routes.get_price_chart_history(symbol="AAPL", interval="1D")

    assert payload.source == "local"
    assert payload.fallback_used is True
