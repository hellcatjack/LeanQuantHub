from __future__ import annotations

from pathlib import Path
import sys

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import ib_market
from app.services import price_chart_history


@pytest.fixture()
def adjusted_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_root = tmp_path / "data"
    adjusted_root = data_root / "curated_adjusted"
    adjusted_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(price_chart_history.settings, "data_root", str(data_root))
    return adjusted_root


def _write_adjusted_daily(path: Path, symbol: str, rows: list[tuple[str, float, float, float, float, int]]) -> None:
    lines = ["date,open,high,low,close,volume,symbol"]
    for date, open_, high, low, close, volume in rows:
        lines.append(f"{date},{open_},{high},{low},{close},{volume},{symbol}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_interval_1m_maps_to_intraday_ib_request():
    request = price_chart_history.build_chart_request(symbol="AAPL", interval="1m")

    assert request.symbol == "AAPL"
    assert request.interval == "1m"
    assert request.ib_bar_size == "1 min"
    assert request.ib_duration == "1 D"
    assert request.allow_local_fallback is False
    assert request.range_label == "1D"


def test_daily_interval_falls_back_to_local_adjusted_data(
    adjusted_data_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _write_adjusted_daily(
        adjusted_data_root / "999_Alpha_AAPL_Daily.csv",
        "AAPL",
        [
            ("2026-03-05", 188.0, 190.0, 187.5, 189.2, 1200000),
            ("2026-03-06", 189.5, 191.0, 188.2, 190.8, 1500000),
            ("2026-03-09", 191.1, 193.3, 190.7, 192.4, 1800000),
        ],
    )

    monkeypatch.setattr(
        price_chart_history,
        "fetch_historical_bars",
        lambda *_args, **_kwargs: {
            "symbol": "AAPL",
            "bars": 0,
            "path": None,
            "error": "unsupported",
        },
    )

    result = price_chart_history.load_chart_history(symbol="AAPL", interval="1D", mode="paper")

    assert result["symbol"] == "AAPL"
    assert result["interval"] == "1D"
    assert result["source"] == "local"
    assert result["fallback_used"] is True
    assert result["error"] is None
    assert len(result["bars"]) == 3
    assert result["bars"][-1]["close"] == pytest.approx(192.4)
    assert result["meta"]["range_label"] == "6M"


def test_daily_interval_prefers_ib_history_when_available(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        price_chart_history,
        "fetch_historical_bars",
        lambda *_args, **_kwargs: {
            "symbol": "AAPL",
            "bars": 2,
            "items": [
                {
                    "time": 1773097200,
                    "open": 189.5,
                    "high": 191.0,
                    "low": 188.2,
                    "close": 190.8,
                    "volume": 1500000,
                },
                {
                    "time": 1773356400,
                    "open": 191.1,
                    "high": 193.3,
                    "low": 190.7,
                    "close": 192.4,
                    "volume": 1800000,
                },
            ],
            "path": None,
            "error": None,
        },
    )

    result = price_chart_history.load_chart_history(symbol="AAPL", interval="1D", mode="paper")

    assert result["source"] == "ib"
    assert result["fallback_used"] is False
    assert result["error"] is None
    assert len(result["bars"]) == 2
    assert result["bars"][-1]["close"] == pytest.approx(192.4)


def test_intraday_interval_returns_unavailable_when_ib_history_fails(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        price_chart_history,
        "fetch_historical_bars",
        lambda *_args, **_kwargs: {
            "symbol": "AAPL",
            "bars": 0,
            "path": None,
            "error": "unsupported",
        },
    )

    result = price_chart_history.load_chart_history(symbol="AAPL", interval="1m", mode="paper")

    assert result["source"] == "unavailable"
    assert result["fallback_used"] is False
    assert result["error"] == "ib_history_unavailable"
    assert result["bars"] == []


def test_fetch_historical_bars_uses_ib_read_session(monkeypatch: pytest.MonkeyPatch):
    class _Settings:
        host = "127.0.0.1"
        port = 4002

    class _ReadSession:
        def fetch_historical_bars(self, **kwargs):
            assert kwargs["symbol"] == "AAPL"
            assert kwargs["duration"] == "1 D"
            assert kwargs["bar_size"] == "1 min"
            return [
                {
                    "time": 1773356400,
                    "open": 191.1,
                    "high": 193.3,
                    "low": 190.7,
                    "close": 192.4,
                    "volume": 1800000,
                }
            ]

    monkeypatch.setattr(ib_market, "get_or_create_ib_settings", lambda _session: _Settings(), raising=False)
    monkeypatch.setattr(ib_market, "get_ib_read_session", lambda **_kwargs: _ReadSession(), raising=False)

    result = ib_market.fetch_historical_bars(
        object(),
        symbol="AAPL",
        duration="1 D",
        bar_size="1 min",
        use_rth=True,
        store=False,
    )

    assert result["symbol"] == "AAPL"
    assert result["bars"] == 1
    assert result["error"] is None
    assert result["items"][0]["close"] == pytest.approx(192.4)


def test_intraday_interval_prefers_ib_history_when_available(monkeypatch: pytest.MonkeyPatch):
    class _FakeSettings:
        host = "127.0.0.1"
        port = 4002
        mode = "paper"

    class _FakeReadSession:
        def fetch_historical_bars(self, **kwargs):
            assert kwargs["symbol"] == "AAPL"
            assert kwargs["duration"] == "1 D"
            assert kwargs["bar_size"] == "1 min"
            return [
                {
                    "time": 1773187200,
                    "open": 188.92,
                    "high": 189.10,
                    "low": 188.50,
                    "close": 188.75,
                    "volume": 582000,
                }
            ]

    monkeypatch.setattr(ib_market, "get_or_create_ib_settings", lambda _session: _FakeSettings(), raising=False)
    monkeypatch.setattr(
        ib_market,
        "get_ib_read_session",
        lambda **_kwargs: _FakeReadSession(),
        raising=False,
    )

    result = price_chart_history.load_chart_history(symbol="AAPL", interval="1m", mode="paper", session=object())

    assert result["source"] == "ib"
    assert result["fallback_used"] is False
    assert result["error"] is None
    assert len(result["bars"]) == 1
    assert result["bars"][0]["close"] == pytest.approx(188.75)
