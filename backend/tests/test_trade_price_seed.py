from app.services import trade_price_seed


def test_build_price_seed_map_prefers_bridge_quotes(monkeypatch):
    monkeypatch.setattr(
        trade_price_seed,
        "read_quotes",
        lambda *_args, **_kwargs: {
            "items": [
                {"symbol": "AAPL", "data": {"last": 189.2}},
                {"symbol": "MSFT", "data": {"bid": 412.1, "ask": 412.3}},
            ]
        },
        raising=False,
    )
    monkeypatch.setattr(trade_price_seed, "_load_fallback_prices", lambda _symbols: {}, raising=False)

    result = trade_price_seed.build_price_seed_map(["AAPL", "MSFT"])
    assert result["AAPL"] == 189.2
    assert result["MSFT"] == 412.1


def test_build_price_seed_map_falls_back_when_quote_missing(monkeypatch):
    monkeypatch.setattr(trade_price_seed, "read_quotes", lambda *_args, **_kwargs: {"items": []}, raising=False)
    monkeypatch.setattr(trade_price_seed, "_load_fallback_prices", lambda _symbols: {"WDC": 274.5}, raising=False)

    result = trade_price_seed.build_price_seed_map(["WDC"])
    assert result["WDC"] == 274.5
