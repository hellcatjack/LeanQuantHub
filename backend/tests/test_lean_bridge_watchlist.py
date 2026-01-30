from app.services import project_symbols


def test_build_leader_watchlist_hard_cap_round_robin(monkeypatch):
    projects = [
        {"id": 1, "benchmark": "SPY", "symbols": ["A", "B", "C", "D"]},
        {"id": 2, "benchmark": "QQQ", "symbols": ["A", "E", "F"]},
        {"id": 3, "benchmark": "IWM", "symbols": ["G"]},
    ]

    def _fake_collect_active(_session):
        return projects

    monkeypatch.setattr(project_symbols, "_collect_active_project_watchlist_inputs", _fake_collect_active)

    result = project_symbols.build_leader_watchlist(None, max_symbols=5)

    assert result[:3] == ["SPY", "QQQ", "IWM"]
    assert result[3:] == ["A", "E"]
    assert len(result) == 5
    assert len(set(result)) == 5


def test_build_leader_watchlist_fallback_spy(monkeypatch):
    def _fake_collect_active(_session):
        return []

    monkeypatch.setattr(project_symbols, "_collect_active_project_watchlist_inputs", _fake_collect_active)

    result = project_symbols.build_leader_watchlist(None, max_symbols=200)

    assert result == ["SPY"]


def test_build_leader_watchlist_dedupes_benchmark(monkeypatch):
    projects = [
        {"id": 1, "benchmark": "SPY", "symbols": ["SPY", "AAPL"]},
        {"id": 2, "benchmark": "SPY", "symbols": ["MSFT"]},
    ]

    def _fake_collect_active(_session):
        return projects

    monkeypatch.setattr(project_symbols, "_collect_active_project_watchlist_inputs", _fake_collect_active)

    result = project_symbols.build_leader_watchlist(None, max_symbols=10)

    assert result[0] == "SPY"
    assert result.count("SPY") == 1
    assert "AAPL" in result
    assert "MSFT" in result


def test_build_leader_watchlist_prioritizes_snapshot_symbols(monkeypatch):
    projects = [
        {"id": 1, "benchmark": "SPY", "symbols": ["A", "B"], "snapshot_symbols": ["X", "Y"]},
        {"id": 2, "benchmark": "QQQ", "symbols": ["C"], "snapshot_symbols": ["Z"]},
    ]

    def _fake_collect_active(_session):
        return projects

    monkeypatch.setattr(project_symbols, "_collect_active_project_watchlist_inputs", _fake_collect_active)

    result = project_symbols.build_leader_watchlist(None, max_symbols=5)

    assert result == ["SPY", "QQQ", "X", "Z", "Y"]


def test_refresh_leader_watchlist_skips_write_on_same_symbols(tmp_path, monkeypatch):
    from app.services import lean_bridge_watchlist

    watchlist_path = tmp_path / "watchlist.json"
    watchlist_path.write_text(
        '{"symbols": ["AAPL"], "updated_at": "2020-01-01T00:00:00Z"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        lean_bridge_watchlist,
        "build_leader_watchlist",
        lambda *_args, **_kwargs: ["AAPL"],
    )

    payload = lean_bridge_watchlist.refresh_leader_watchlist(
        None, max_symbols=200, bridge_root=tmp_path
    )

    assert payload.get("updated_at") == "2020-01-01T00:00:00Z"


def test_refresh_leader_watchlist_writes_when_changed(tmp_path, monkeypatch):
    from app.services import lean_bridge_watchlist

    monkeypatch.setattr(
        lean_bridge_watchlist,
        "build_leader_watchlist",
        lambda *_args, **_kwargs: ["MSFT"],
    )

    payload = lean_bridge_watchlist.refresh_leader_watchlist(
        None, max_symbols=200, bridge_root=tmp_path
    )

    assert payload.get("symbols") == ["MSFT"]
    assert payload.get("updated_at")
