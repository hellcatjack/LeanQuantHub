from __future__ import annotations

from contextlib import contextmanager

from app.services import ib_stream


def test_run_stream_once_writes_tick(tmp_path):
    def fake_fetcher(session, *, symbols, **kwargs):
        assert symbols == ["AAPL", "MSFT"]
        return [
            {"symbol": "AAPL", "data": {"last": 123.4, "source": "unit"}, "error": None},
            {"symbol": "MSFT", "data": None, "error": "no_data"},
        ]

    @contextmanager
    def fake_session_factory():
        yield object()

    result = ib_stream.run_stream_once(
        project_id=1,
        decision_snapshot_id=None,
        symbols=["AAPL", "MSFT"],
        max_symbols=None,
        data_root=tmp_path,
        api_mode="mock",
        market_data_type="delayed",
        fetcher=fake_fetcher,
        session_factory=fake_session_factory,
    )

    assert result["symbols"] == ["AAPL", "MSFT"]
    assert result["count"] == 2
    assert result["errors"] == ["MSFT:no_data"]
    assert (tmp_path / "stream" / "AAPL.json").exists()
    assert not (tmp_path / "stream" / "MSFT.json").exists()
