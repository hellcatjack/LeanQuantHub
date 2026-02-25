from pathlib import Path
import sys
import threading
import time

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True)
def _reset_account_positions_response_cache():
    from app.services import ib_account as ib_account_module

    ib_account_module._clear_account_positions_response_cache()
    yield
    ib_account_module._clear_account_positions_response_cache()


def test_ib_account_summary_uses_bridge(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_account_summary",
        lambda _root: {"items": [{"name": "Net", "value": 1}], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))

    payload = ib_account_module.get_account_summary(
        session=None, mode="paper", full=False, force_refresh=False
    )
    assert payload["items"]["Net"] == 1
    assert payload["stale"] is False


def test_ib_account_positions_uses_bridge(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_positions",
        lambda _root: {
            "items": [{"symbol": "AAA", "quantity": 2, "market_value": 10}],
            "stale": False,
            "source_detail": "ib_holdings",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))

    payload = ib_account_module.get_account_positions(
        session=None, mode="paper", force_refresh=False
    )
    assert payload["items"][0]["symbol"] == "AAA"
    assert payload["items"][0]["position"] == 2
    assert payload["items"][0]["market_price"] == 5
    assert payload["stale"] is False


def test_ib_account_positions_fill_from_quotes(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_positions",
        lambda _root: {
            "items": [
                {
                    "symbol": "AAA",
                    "quantity": 2,
                    "avg_cost": 10,
                    "market_value": 0,
                    "unrealized_pnl": 0,
                }
            ],
            "stale": False,
            "source_detail": "ib_holdings",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [{"symbol": "AAA", "last": 12.5}], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))

    payload = ib_account_module.get_account_positions(
        session=None, mode="paper", force_refresh=False
    )
    row = payload["items"][0]
    assert row["market_price"] == 12.5
    assert row["market_value"] == 25.0
    assert row["unrealized_pnl"] == 5.0


def test_ib_account_positions_rejects_non_ib_holdings(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_positions",
        lambda _root: {
            "items": [{"symbol": "AAA", "quantity": 2, "market_value": 10}],
            "stale": False,
            "source_detail": "algorithm_holdings",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))

    payload = ib_account_module.get_account_positions(
        session=None, mode="paper", force_refresh=False
    )
    assert payload["items"] == []
    assert payload["stale"] is True


def test_ib_account_positions_accepts_ib_holdings_empty(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_positions",
        lambda _root: {
            "items": [],
            "stale": False,
            "source_detail": "ib_holdings_empty",
            "refreshed_at": "2026-02-11T19:23:00Z",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))

    payload = ib_account_module.get_account_positions(
        session=None, mode="paper", force_refresh=False
    )
    assert payload["items"] == []
    assert payload["stale"] is False
    assert payload["source_detail"] == "ib_holdings_empty"


def test_ib_account_positions_force_refresh_triggers_bridge_refresh(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    calls = {"ensure": 0}

    monkeypatch.setattr(
        ib_account_module,
        "read_positions",
        lambda _root: {
            "items": [{"symbol": "AAA", "quantity": 2, "market_value": 10}],
            "stale": False,
            "source_detail": "ib_holdings",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(
        ib_account_module,
        "ensure_positions_baseline",
        lambda _root, _payload: {},
    )
    monkeypatch.setattr(
        ib_account_module,
        "compute_realized_pnl",
        lambda _session, _baseline: type("Realized", (), {"symbol_totals": {}})(),
    )
    monkeypatch.setattr(
        ib_account_module,
        "_reconcile_non_stale_ib_holdings_with_recent_fills",
        lambda _session, *, mode, payload: payload,
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(
        ib_account_module,
        "_is_positions_snapshot_inconsistent_with_recent_fills",
        lambda *_args, **_kwargs: False,
    )

    def _fake_ensure(_session, *, mode: str, force: bool = False):
        calls["ensure"] += 1
        return {"status": "ok"}

    monkeypatch.setattr(ib_account_module, "ensure_lean_bridge_live", _fake_ensure)

    class _DummySession:
        pass

    payload = ib_account_module.get_account_positions(
        session=_DummySession(), mode="paper", force_refresh=True
    )
    assert calls["ensure"] == 1
    assert payload["items"][0]["symbol"] == "AAA"


def test_ib_account_positions_prefers_ibapi_when_non_stale_snapshot_mismatches(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_positions",
        lambda _root: {
            "items": [{"symbol": "AAA", "quantity": 2}],
            "stale": False,
            "source_detail": "ib_holdings",
            "refreshed_at": "2026-02-13T15:41:00Z",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(
        ib_account_module,
        "ensure_positions_baseline",
        lambda _root, _payload: {},
    )
    monkeypatch.setattr(
        ib_account_module,
        "compute_realized_pnl",
        lambda _session, _baseline: type("Realized", (), {"symbol_totals": {}})(),
    )
    monkeypatch.setattr(
        ib_account_module,
        "_reconcile_non_stale_ib_holdings_with_recent_fills",
        lambda _session, *, mode, payload: payload,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_positions_via_ibapi_verified",
        lambda _session, *, mode, refreshed_at, force=False: {
            "items": [{"symbol": "BBB", "position": 3.0, "quantity": 3.0}],
            "refreshed_at": refreshed_at,
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
        },
    )

    class _DummySession:
        def query(self, *_args, **_kwargs):
            return None

    payload = ib_account_module.get_account_positions(
        session=_DummySession(), mode="paper", force_refresh=False
    )
    assert payload["stale"] is False
    assert payload["source_detail"] == "ib_holdings_ibapi_fallback"
    assert payload["items"][0]["symbol"] == "BBB"
    assert payload["items"][0]["position"] == 3.0


def test_ib_account_positions_keeps_bridge_when_non_stale_snapshot_matches_ibapi(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_positions",
        lambda _root: {
            "items": [{"symbol": "AAA", "quantity": 2}],
            "stale": False,
            "source_detail": "ib_holdings",
            "refreshed_at": "2026-02-13T15:42:00Z",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(
        ib_account_module,
        "ensure_positions_baseline",
        lambda _root, _payload: {},
    )
    monkeypatch.setattr(
        ib_account_module,
        "compute_realized_pnl",
        lambda _session, _baseline: type("Realized", (), {"symbol_totals": {}})(),
    )
    monkeypatch.setattr(
        ib_account_module,
        "_reconcile_non_stale_ib_holdings_with_recent_fills",
        lambda _session, *, mode, payload: payload,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_positions_via_ibapi_verified",
        lambda _session, *, mode, refreshed_at, force=False: {
            "items": [{"symbol": "AAA", "position": 2.0, "quantity": 2.0}],
            "refreshed_at": refreshed_at,
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
        },
    )

    class _DummySession:
        def query(self, *_args, **_kwargs):
            return None

    payload = ib_account_module.get_account_positions(
        session=_DummySession(), mode="paper", force_refresh=False
    )
    assert payload["stale"] is False
    assert payload["source_detail"] == "ib_holdings"
    assert payload["items"][0]["symbol"] == "AAA"
    assert payload["items"][0]["position"] == 2.0


def test_ib_account_positions_includes_zero_quantity_from_ibapi_verified_when_ibapi_payload_selected(
    monkeypatch,
):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_positions",
        lambda _root: {
            "items": [{"symbol": "AAA", "quantity": 2}],
            "stale": False,
            "source_detail": "ib_holdings",
            "refreshed_at": "2026-02-13T15:42:00Z",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(
        ib_account_module,
        "ensure_positions_baseline",
        lambda _root, _payload: {},
    )
    monkeypatch.setattr(
        ib_account_module,
        "compute_realized_pnl",
        lambda _session, _baseline: type("Realized", (), {"symbol_totals": {}})(),
    )
    monkeypatch.setattr(
        ib_account_module,
        "_reconcile_non_stale_ib_holdings_with_recent_fills",
        lambda _session, *, mode, payload: payload,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_positions_via_ibapi_verified",
        lambda _session, *, mode, refreshed_at, force=False: {
            "items": [
                {"symbol": "BBB", "position": 3.0, "quantity": 3.0},
                {"symbol": "ZERO", "position": 0.0, "quantity": 0.0},
            ],
            "refreshed_at": refreshed_at,
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
        },
    )

    class _DummySession:
        def query(self, *_args, **_kwargs):
            return None

    payload = ib_account_module.get_account_positions(
        session=_DummySession(), mode="paper", force_refresh=False
    )

    assert payload["stale"] is False
    assert payload["source_detail"] == "ib_holdings_ibapi_fallback"
    by_symbol = {str(item["symbol"]): item for item in payload["items"]}
    assert "BBB" in by_symbol
    assert "ZERO" in by_symbol
    assert by_symbol["ZERO"]["position"] == 0.0


def test_ib_account_positions_prefers_ibapi_when_only_flat_symbols_missing_from_bridge(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_positions",
        lambda _root: {
            "items": [{"symbol": "AAA", "quantity": 2}],
            "stale": False,
            "source_detail": "ib_holdings",
            "refreshed_at": "2026-02-13T15:42:00Z",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(
        ib_account_module,
        "ensure_positions_baseline",
        lambda _root, _payload: {},
    )
    monkeypatch.setattr(
        ib_account_module,
        "compute_realized_pnl",
        lambda _session, _baseline: type("Realized", (), {"symbol_totals": {}})(),
    )
    monkeypatch.setattr(
        ib_account_module,
        "_reconcile_non_stale_ib_holdings_with_recent_fills",
        lambda _session, *, mode, payload: payload,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_positions_via_ibapi_verified",
        lambda _session, *, mode, refreshed_at, force=False: {
            "items": [
                {"symbol": "AAA", "position": 2.0, "quantity": 2.0},
                {"symbol": "ZERO", "position": 0.0, "quantity": 0.0},
            ],
            "refreshed_at": refreshed_at,
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
        },
    )

    class _DummySession:
        def query(self, *_args, **_kwargs):
            return None

    payload = ib_account_module.get_account_positions(
        session=_DummySession(), mode="paper", force_refresh=False
    )

    assert payload["stale"] is False
    assert payload["source_detail"] == "ib_holdings_ibapi_fallback"
    by_symbol = {str(item["symbol"]): item for item in payload["items"]}
    assert "AAA" in by_symbol
    assert "ZERO" in by_symbol
    assert by_symbol["ZERO"]["position"] == 0.0


def test_ib_account_positions_prefers_ibapi_when_flat_symbol_differs(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_positions",
        lambda _root: {
            "items": [
                {"symbol": "AAA", "quantity": 2},
                {"symbol": "ZERO", "quantity": 0},
            ],
            "stale": False,
            "source_detail": "ib_holdings",
            "refreshed_at": "2026-02-13T15:42:00Z",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(
        ib_account_module,
        "ensure_positions_baseline",
        lambda _root, _payload: {},
    )
    monkeypatch.setattr(
        ib_account_module,
        "compute_realized_pnl",
        lambda _session, _baseline: type("Realized", (), {"symbol_totals": {}})(),
    )
    monkeypatch.setattr(
        ib_account_module,
        "_reconcile_non_stale_ib_holdings_with_recent_fills",
        lambda _session, *, mode, payload: payload,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_positions_via_ibapi_verified",
        lambda _session, *, mode, refreshed_at, force=False: {
            "items": [{"symbol": "AAA", "position": 2.0, "quantity": 2.0}],
            "refreshed_at": refreshed_at,
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
        },
    )

    class _DummySession:
        def query(self, *_args, **_kwargs):
            return None

    payload = ib_account_module.get_account_positions(
        session=_DummySession(), mode="paper", force_refresh=False
    )

    assert payload["stale"] is False
    assert payload["source_detail"] == "ib_holdings_ibapi_fallback"
    by_symbol = {str(item["symbol"]): item for item in payload["items"]}
    assert "ZERO" not in by_symbol


def test_ib_account_positions_stale_snapshot_returns_fast_without_ibapi_probe(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    class _DummySession:
        pass

    read_calls = {"count": 0}

    def _fake_read_positions(_root):
        read_calls["count"] += 1
        # Simulate bridge snapshot stuck on stale holdings.
        return {
            "items": [{"symbol": "OLD", "quantity": 9, "market_value": 90}],
            "stale": True,
            "source_detail": "ib_holdings",
            "refreshed_at": "2026-02-13T14:00:00Z",
        }

    monkeypatch.setattr(ib_account_module, "read_positions", _fake_read_positions)
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(
        ib_account_module,
        "ensure_positions_baseline",
        lambda _root, _payload: {},
    )
    monkeypatch.setattr(
        ib_account_module,
        "compute_realized_pnl",
        lambda _session, _baseline: type("Realized", (), {"symbol_totals": {}})(),
    )
    calls = {"ensure_force": [], "timeout_seconds": []}

    def _fake_ensure(_session, *, mode, force=False):
        calls["ensure_force"].append(bool(force))
        return {"status": "ok", "mode": mode, "force": force}

    monkeypatch.setattr(
        ib_account_module,
        "ensure_lean_bridge_live",
        _fake_ensure,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_positions_via_ibapi_fallback",
        lambda _session, *, mode, refreshed_at, timeout_seconds=6.0: (
            calls["timeout_seconds"].append(float(timeout_seconds))
            or {
            "items": [{"symbol": "NEW", "position": 3, "avg_cost": 11.0}],
            "refreshed_at": refreshed_at,
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
        }),
    )

    payload = ib_account_module.get_account_positions(
        session=_DummySession(), mode="paper", force_refresh=False
    )

    assert read_calls["count"] == 1
    assert calls["ensure_force"] == []
    assert calls["timeout_seconds"] == []
    assert payload["stale"] is True
    assert payload["source_detail"] == "ib_holdings"
    assert payload["items"] and payload["items"][0]["symbol"] == "OLD"


def test_ib_account_positions_cached_reuses_recent_payload(monkeypatch):
    from app.services import ib_account as ib_account_module

    calls = {"count": 0}

    def _fake_get_account_positions(_session, *, mode: str, force_refresh: bool = False):
        calls["count"] += 1
        return {
            "items": [{"symbol": "AAA", "position": 1.0}],
            "refreshed_at": "2026-02-12T18:00:00Z",
            "stale": False,
            "source_detail": "ib_holdings",
        }

    monkeypatch.setattr(ib_account_module, "get_account_positions", _fake_get_account_positions)

    first = ib_account_module.get_account_positions_cached(session=None, mode="paper", force_refresh=False)
    first["items"][0]["symbol"] = "CHANGED"
    second = ib_account_module.get_account_positions_cached(session=None, mode="paper", force_refresh=False)

    assert calls["count"] == 1
    assert second["items"][0]["symbol"] == "AAA"
    assert second["items"][0]["position"] == 1.0


def test_ib_account_positions_cached_force_refresh_bypasses_cache(monkeypatch):
    from app.services import ib_account as ib_account_module

    calls = {"count": 0}
    payloads = iter(
        [
            {
                "items": [{"symbol": "AAA", "position": 1.0}],
                "refreshed_at": "2026-02-12T18:00:00Z",
                "stale": False,
                "source_detail": "ib_holdings",
            },
            {
                "items": [{"symbol": "AAA", "position": 2.0}],
                "refreshed_at": "2026-02-12T18:00:02Z",
                "stale": False,
                "source_detail": "ib_holdings",
            },
        ]
    )

    def _fake_get_account_positions(_session, *, mode: str, force_refresh: bool = False):
        calls["count"] += 1
        return next(payloads)

    monkeypatch.setattr(ib_account_module, "get_account_positions", _fake_get_account_positions)

    initial = ib_account_module.get_account_positions_cached(session=None, mode="paper", force_refresh=False)
    cached = ib_account_module.get_account_positions_cached(session=None, mode="paper", force_refresh=False)
    refreshed = ib_account_module.get_account_positions_cached(session=None, mode="paper", force_refresh=True)
    post_refresh = ib_account_module.get_account_positions_cached(session=None, mode="paper", force_refresh=False)

    assert calls["count"] == 2
    assert initial["items"][0]["position"] == 1.0
    assert cached["items"][0]["position"] == 1.0
    assert refreshed["items"][0]["position"] == 2.0
    assert post_refresh["items"][0]["position"] == 2.0


def test_ib_account_positions_cached_follower_returns_when_owner_stalled(monkeypatch):
    from app.services import ib_account as ib_account_module

    calls = {"count": 0}
    owner_gate = threading.Event()
    owner_entered = threading.Event()

    monkeypatch.setattr(
        ib_account_module,
        "_ACCOUNT_POSITIONS_RESPONSE_CACHE_TTL_SECONDS",
        0.1,
        raising=False,
    )

    def _fake_get_account_positions(_session, *, mode: str, force_refresh: bool = False):
        calls["count"] += 1
        if calls["count"] == 1:
            owner_entered.set()
            owner_gate.wait(timeout=5)
        return {
            "items": [{"symbol": "AAA", "position": 1.0}],
            "refreshed_at": "2026-02-12T18:00:00Z",
            "stale": False,
            "source_detail": "ib_holdings",
        }

    monkeypatch.setattr(ib_account_module, "get_account_positions", _fake_get_account_positions)

    owner_result: dict[str, object] = {}
    follower_result: dict[str, object] = {}
    follower_done = threading.Event()

    def _owner():
        owner_result["payload"] = ib_account_module.get_account_positions_cached(
            session=None,
            mode="paper",
            force_refresh=False,
        )

    def _follower():
        started = time.monotonic()
        follower_result["payload"] = ib_account_module.get_account_positions_cached(
            session=None,
            mode="paper",
            force_refresh=False,
        )
        follower_result["elapsed"] = time.monotonic() - started
        follower_done.set()

    owner_thread = threading.Thread(target=_owner, daemon=True)
    follower_thread = threading.Thread(target=_follower, daemon=True)

    owner_thread.start()
    assert owner_entered.wait(timeout=0.5)
    follower_thread.start()

    try:
        assert follower_done.wait(timeout=0.6), "follower request blocked by stalled cache owner"
        assert float(follower_result.get("elapsed", 10.0)) < 0.6
    finally:
        owner_gate.set()
        owner_thread.join(timeout=2)
        follower_thread.join(timeout=2)


def test_ib_account_positions_keeps_stale_ib_holdings_snapshot(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    payloads = iter(
        [
            {
                "items": [{"symbol": "AAA", "quantity": 2, "market_value": 10}],
                "stale": True,
                "source_detail": "ib_holdings",
                "refreshed_at": "2026-02-11T19:00:00Z",
            },
            {
                "items": [{"symbol": "AAA", "quantity": 2, "market_value": 10}],
                "stale": True,
                "source_detail": "ib_holdings",
                "refreshed_at": "2026-02-11T19:00:05Z",
            },
        ]
    )

    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(ib_account_module, "read_positions", lambda _root: next(payloads))
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(
        ib_account_module,
        "ensure_positions_baseline",
        lambda _root, _payload: {},
    )
    monkeypatch.setattr(
        ib_account_module,
        "compute_realized_pnl",
        lambda _session, _baseline: type("Realized", (), {"symbol_totals": {}})(),
    )
    monkeypatch.setattr(
        ib_account_module,
        "_infer_positions_from_recent_direct_fills",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should_not_infer")),
    )

    calls = {"ensure": 0, "ibapi": 0}

    def _fake_ensure(_session, *, mode: str, force: bool = False):
        calls["ensure"] += 1
        return {"status": "ok"}

    def _fake_ibapi(*_args, **_kwargs):
        calls["ibapi"] += 1
        return None

    monkeypatch.setattr(ib_account_module, "ensure_lean_bridge_live", _fake_ensure)
    monkeypatch.setattr(ib_account_module, "_load_positions_via_ibapi_fallback", _fake_ibapi)

    class _DummySession:
        pass

    payload = ib_account_module.get_account_positions(
        session=_DummySession(), mode="paper", force_refresh=False
    )
    assert calls["ensure"] == 0
    assert calls["ibapi"] == 0
    assert payload["items"][0]["symbol"] == "AAA"
    assert payload["items"][0]["position"] == 2
    assert payload["stale"] is True


def test_ib_account_positions_keeps_non_stale_ib_holdings_when_inconsistent_if_ibapi_unavailable(
    monkeypatch,
):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    payloads = iter(
        [
            {
                "items": [{"symbol": "AAA", "quantity": 2, "market_value": 10}],
                "stale": False,
                "source_detail": "ib_holdings",
                "refreshed_at": "2026-02-11T19:20:00Z",
            },
            {
                "items": [{"symbol": "AAA", "quantity": 2, "market_value": 10}],
                "stale": False,
                "source_detail": "ib_holdings",
                "refreshed_at": "2026-02-11T19:20:05Z",
            },
        ]
    )
    monkeypatch.setattr(ib_account_module, "read_positions", lambda _root: next(payloads))
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(
        ib_account_module,
        "ensure_positions_baseline",
        lambda _root, _payload: {},
    )
    monkeypatch.setattr(
        ib_account_module,
        "compute_realized_pnl",
        lambda _session, _baseline: type("Realized", (), {"symbol_totals": {}})(),
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(
        ib_account_module,
        "_is_positions_snapshot_inconsistent_with_recent_fills",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_positions_via_ibapi_fallback",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_infer_positions_from_recent_direct_fills",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should_not_infer")),
    )

    calls = {"ensure": 0}

    def _fake_ensure(_session, *, mode: str, force: bool = False):
        calls["ensure"] += 1
        return {"status": "ok"}

    monkeypatch.setattr(ib_account_module, "ensure_lean_bridge_live", _fake_ensure)

    class _DummySession:
        pass

    payload = ib_account_module.get_account_positions(
        session=_DummySession(), mode="paper", force_refresh=False
    )
    assert calls["ensure"] == 0
    assert payload["items"][0]["symbol"] == "AAA"
    assert payload["items"][0]["position"] == 2
    assert payload["stale"] is False
    assert payload["source_detail"] == "ib_holdings"


def test_ib_account_positions_inconsistent_non_stale_snapshot_does_not_remove_symbol_via_overlay(
    monkeypatch,
):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    payloads = iter(
        [
            {
                "items": [{"symbol": "AAA", "quantity": 2, "market_value": 10}],
                "stale": False,
                "source_detail": "ib_holdings",
                "refreshed_at": "2026-02-11T19:20:00Z",
            },
            {
                "items": [{"symbol": "AAA", "quantity": 2, "market_value": 10}],
                "stale": False,
                "source_detail": "ib_holdings",
                "refreshed_at": "2026-02-11T19:20:05Z",
            },
        ]
    )
    monkeypatch.setattr(ib_account_module, "read_positions", lambda _root: next(payloads))
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [{"symbol": "AAA", "last": 5.0}], "stale": False},
    )
    monkeypatch.setattr(
        ib_account_module,
        "ensure_positions_baseline",
        lambda _root, _payload: {},
    )
    monkeypatch.setattr(
        ib_account_module,
        "compute_realized_pnl",
        lambda _session, _baseline: type("Realized", (), {"symbol_totals": {}})(),
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(
        ib_account_module,
        "_is_positions_snapshot_inconsistent_with_recent_fills",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_positions_via_ibapi_fallback",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_infer_positions_from_recent_direct_fills",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should_not_infer")),
    )

    calls = {"ensure": 0}

    def _fake_ensure(_session, *, mode: str, force: bool = False):
        calls["ensure"] += 1
        return {"status": "ok"}

    monkeypatch.setattr(ib_account_module, "ensure_lean_bridge_live", _fake_ensure)

    class _DummySession:
        pass

    payload = ib_account_module.get_account_positions(
        session=_DummySession(), mode="paper", force_refresh=False
    )
    assert calls["ensure"] == 0
    assert payload["source_detail"] == "ib_holdings"
    assert payload["stale"] is False
    assert payload["items"] and payload["items"][0]["symbol"] == "AAA"


def test_ib_account_positions_prefers_ibapi_fallback_when_inconsistent(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    payloads = iter(
        [
            {
                "items": [{"symbol": "AAA", "quantity": 2, "market_value": 10}],
                "stale": False,
                "source_detail": "ib_holdings",
                "refreshed_at": "2026-02-13T14:58:00Z",
            },
            {
                "items": [{"symbol": "AAA", "quantity": 2, "market_value": 10}],
                "stale": False,
                "source_detail": "ib_holdings",
                "refreshed_at": "2026-02-13T14:58:05Z",
            },
        ]
    )
    monkeypatch.setattr(ib_account_module, "read_positions", lambda _root: next(payloads))
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(
        ib_account_module,
        "ensure_positions_baseline",
        lambda _root, _payload: {},
    )
    monkeypatch.setattr(
        ib_account_module,
        "compute_realized_pnl",
        lambda _session, _baseline: type("Realized", (), {"symbol_totals": {}})(),
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(
        ib_account_module,
        "_load_positions_via_ibapi_verified",
        lambda *_args, **_kwargs: {
            "items": [{"symbol": "BBB", "position": 3.0, "quantity": 3.0}],
            "refreshed_at": "2026-02-13T14:58:09Z",
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "_infer_positions_from_recent_direct_fills",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should_not_infer")),
    )

    calls = {"ensure": 0}

    def _fake_ensure(_session, *, mode: str, force: bool = False):
        calls["ensure"] += 1
        return {"status": "ok"}

    monkeypatch.setattr(ib_account_module, "ensure_lean_bridge_live", _fake_ensure)

    class _DummySession:
        def query(self, *_args, **_kwargs):
            return None

    payload = ib_account_module.get_account_positions(
        session=_DummySession(), mode="paper", force_refresh=False
    )
    assert calls["ensure"] == 0
    assert payload["source_detail"] == "ib_holdings_ibapi_fallback"
    assert payload["stale"] is False
    assert payload["items"][0]["symbol"] == "BBB"


def test_ib_account_positions_skips_redundant_verify_for_ibapi_fallback_snapshot(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    monkeypatch.setattr(
        ib_account_module,
        "read_positions",
        lambda _root: {
            "items": [{"symbol": "AAA", "quantity": 2}],
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
            "refreshed_at": "2026-02-13T14:58:00Z",
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(
        ib_account_module,
        "ensure_positions_baseline",
        lambda _root, _payload: {},
    )
    monkeypatch.setattr(
        ib_account_module,
        "compute_realized_pnl",
        lambda _session, _baseline: type("Realized", (), {"symbol_totals": {}})(),
    )
    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(
        ib_account_module,
        "_reconcile_non_stale_ib_holdings_with_recent_fills",
        lambda _session, *, mode, payload: payload,
    )

    calls = {"verify": 0}

    def _fake_verify(_session, *, mode, refreshed_at, force=False):
        calls["verify"] += 1
        return {
            "items": [{"symbol": "BBB", "position": 3.0, "quantity": 3.0}],
            "refreshed_at": refreshed_at,
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
        }

    monkeypatch.setattr(ib_account_module, "_load_positions_via_ibapi_verified", _fake_verify)

    class _DummySession:
        def query(self, *_args, **_kwargs):
            return None

    payload = ib_account_module.get_account_positions(
        session=_DummySession(), mode="paper", force_refresh=False
    )
    assert calls["verify"] == 0
    assert payload["source_detail"] == "ib_holdings_ibapi_fallback"
    assert payload["stale"] is False
    assert payload["items"][0]["symbol"] == "AAA"


def test_ib_account_positions_stale_snapshot_does_not_infer_recent_direct_fills(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    payloads = iter(
        [
            {
                "items": [],
                "stale": True,
                "source_detail": "ib_holdings_empty",
                "refreshed_at": "2026-02-12T15:47:09Z",
            },
            {
                "items": [],
                "stale": True,
                "source_detail": "ib_holdings_empty",
                "refreshed_at": "2026-02-12T15:47:12Z",
            },
        ]
    )

    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(ib_account_module, "read_positions", lambda _root: next(payloads))
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [{"symbol": "AAPL", "last": 272.0}], "stale": False},
    )
    monkeypatch.setattr(
        ib_account_module,
        "ensure_positions_baseline",
        lambda _root, _payload: {},
    )
    monkeypatch.setattr(
        ib_account_module,
        "compute_realized_pnl",
        lambda _session, _baseline: type("Realized", (), {"symbol_totals": {}})(),
    )
    monkeypatch.setattr(
        ib_account_module,
        "_infer_positions_from_recent_direct_fills",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should_not_infer")),
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_positions_via_ibapi_fallback",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_is_positions_snapshot_inconsistent_with_recent_fills",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(ib_account_module, "ensure_lean_bridge_live", lambda *_args, **_kwargs: {"status": "ok"})

    class _DummySession:
        pass

    payload = ib_account_module.get_account_positions(
        session=_DummySession(), mode="paper", force_refresh=False
    )
    assert payload["stale"] is True
    assert payload["source_detail"] == "ib_holdings_empty"
    assert payload["items"] == []


def test_ib_account_positions_cached_stalled_owner_uses_canonical_fetch_instead_of_fast_fallback(
    monkeypatch,
):
    from app.services import ib_account as ib_account_module

    wake = threading.Event()
    wake.set()
    monkeypatch.setattr(
        ib_account_module,
        "_ACCOUNT_POSITIONS_RESPONSE_CACHE_TTL_SECONDS",
        0.2,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_get_account_positions_response_cache",
        lambda _key: None,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_acquire_account_positions_response_inflight",
        lambda _key, *, allow_steal_stale=False: (False, wake),
    )
    monkeypatch.setattr(
        ib_account_module,
        "_build_account_positions_fast_fallback",
        lambda *, mode: {
            "items": [{"symbol": "FAST", "position": 9.0}],
            "refreshed_at": "2026-02-13T12:00:00Z",
            "stale": True,
            "source_detail": "ib_holdings_fast_fallback",
            "mode": mode,
        },
    )
    monkeypatch.setattr(
        ib_account_module,
        "get_account_positions",
        lambda _session, *, mode, force_refresh=False: {
            "items": [{"symbol": "AAA", "position": 1.0}],
            "refreshed_at": "2026-02-13T12:00:01Z",
            "stale": False,
            "source_detail": "ib_holdings",
        },
    )

    payload = ib_account_module.get_account_positions_cached(
        session=object(),
        mode="paper",
        force_refresh=False,
    )
    assert payload["source_detail"] == "ib_holdings"
    assert payload["items"][0]["symbol"] == "AAA"


def test_ib_account_positions_non_ib_source_does_not_infer_recent_fills(monkeypatch):
    from pathlib import Path
    from app.services import ib_account as ib_account_module

    payloads = iter(
        [
            {
                "items": [{"symbol": "AAA", "quantity": 2}],
                "stale": True,
                "source_detail": "algorithm_holdings",
                "refreshed_at": "2026-02-12T15:47:09Z",
            },
            {
                "items": [{"symbol": "AAA", "quantity": 2}],
                "stale": True,
                "source_detail": "algorithm_holdings",
                "refreshed_at": "2026-02-12T15:47:12Z",
            },
        ]
    )

    monkeypatch.setattr(ib_account_module, "_resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(ib_account_module, "read_positions", lambda _root: next(payloads))
    monkeypatch.setattr(
        ib_account_module,
        "read_quotes",
        lambda _root: {"items": [], "stale": False},
    )
    monkeypatch.setattr(ib_account_module, "ensure_lean_bridge_live", lambda *_args, **_kwargs: {"status": "ok"})
    monkeypatch.setattr(
        ib_account_module,
        "_infer_positions_from_recent_direct_fills",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should_not_infer")),
    )

    class _DummySession:
        pass

    payload = ib_account_module.get_account_positions(
        session=_DummySession(), mode="paper", force_refresh=False
    )
    assert payload["items"] == []
    assert payload["stale"] is True
    assert payload["source_detail"] == "algorithm_holdings"


def test_inconsistent_check_uses_order_id_tiebreak_when_timestamps_equal(monkeypatch):
    from datetime import datetime
    from app.services import ib_account as ib_account_module

    class _FakeOrder:
        def __init__(self, *, order_id: int, side: str):
            self.id = order_id
            self.run_id = None
            self.status = "FILLED"
            self.symbol = "AAA"
            self.side = side
            self.quantity = 1.0
            self.filled_quantity = 1.0
            self.updated_at = datetime(2026, 2, 12, 19, 17, 34)
            self.params = {"mode": "paper"}

    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def all(self):
            return list(self._rows)

    class _FakeSession:
        def __init__(self, rows):
            self._rows = rows

        def query(self, *_args, **_kwargs):
            return _FakeQuery(self._rows)

    # Lower id BUY + higher id SELL share same timestamp. Latest (higher id) should win.
    orders = [_FakeOrder(order_id=1001, side="BUY"), _FakeOrder(order_id=1002, side="SELL")]
    session = _FakeSession(orders)

    monkeypatch.setattr(
        ib_account_module,
        "_load_direct_order_baseline_qty",
        lambda **_kwargs: 1.0,
    )

    inconsistent = ib_account_module._is_positions_snapshot_inconsistent_with_recent_fills(
        session,
        mode="paper",
        refreshed_at="2026-02-12T19:18:00Z",
        items=[{"symbol": "AAA", "quantity": 0.0}],
    )
    assert inconsistent is False


def test_inconsistent_check_ignores_direct_fill_when_newer_order_exists(monkeypatch):
    from datetime import datetime
    from app.services import ib_account as ib_account_module

    class _FakeOrder:
        def __init__(
            self,
            *,
            order_id: int,
            run_id: int | None,
            side: str,
            updated_at: datetime,
        ):
            self.id = order_id
            self.run_id = run_id
            self.status = "FILLED"
            self.symbol = "AAA"
            self.side = side
            self.quantity = 1.0
            self.filled_quantity = 1.0
            self.updated_at = updated_at
            self.params = {"mode": "paper"}

    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def all(self):
            return list(self._rows)

    class _FakeSession:
        def __init__(self, batches):
            self._batches = iter(batches)

        def query(self, *_args, **_kwargs):
            return _FakeQuery(next(self._batches))

    direct_sell = _FakeOrder(
        order_id=1001,
        run_id=None,
        side="SELL",
        updated_at=datetime(2026, 2, 12, 19, 17, 34),
    )
    newer_run_buy = _FakeOrder(
        order_id=2001,
        run_id=1093,
        side="BUY",
        updated_at=datetime(2026, 2, 12, 19, 20, 0),
    )
    session = _FakeSession(
        [
            [direct_sell],
            [newer_run_buy, direct_sell],
        ]
    )

    monkeypatch.setattr(
        ib_account_module,
        "_load_direct_order_baseline_qty",
        lambda **_kwargs: 1.0,
    )

    inconsistent = ib_account_module._is_positions_snapshot_inconsistent_with_recent_fills(
        session,
        mode="paper",
        refreshed_at="2026-02-12T19:21:00Z",
        items=[{"symbol": "AAA", "quantity": 1.0}],
    )
    assert inconsistent is False


def test_inconsistent_check_ignores_old_direct_fill_for_overlay(monkeypatch):
    from datetime import datetime
    from app.services import ib_account as ib_account_module

    class _FakeOrder:
        def __init__(self, *, order_id: int, side: str, updated_at: datetime):
            self.id = order_id
            self.run_id = None
            self.status = "FILLED"
            self.symbol = "AAA"
            self.side = side
            self.quantity = 1.0
            self.filled_quantity = 1.0
            self.updated_at = updated_at
            self.params = {"mode": "paper"}

    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def all(self):
            return list(self._rows)

    class _FakeSession:
        def __init__(self, batches):
            self._batches = iter(batches)

        def query(self, *_args, **_kwargs):
            return _FakeQuery(next(self._batches))

    old_fill = _FakeOrder(
        order_id=1001,
        side="BUY",
        updated_at=datetime(2026, 2, 12, 19, 5, 0),
    )
    session = _FakeSession(
        [
            [old_fill],
            [old_fill],
        ]
    )

    monkeypatch.setattr(
        ib_account_module,
        "_load_direct_order_baseline_qty",
        lambda **_kwargs: 0.0,
    )

    inconsistent = ib_account_module._is_positions_snapshot_inconsistent_with_recent_fills(
        session,
        mode="paper",
        refreshed_at="2026-02-12T19:21:00Z",
        items=[{"symbol": "AAA", "quantity": 0.0}],
    )
    assert inconsistent is False


def test_inconsistent_check_skips_terminal_fill_without_active_order_after_grace(monkeypatch):
    from datetime import datetime
    from app.services import ib_account as ib_account_module

    class _FakeOrder:
        def __init__(self, *, order_id: int, status: str, side: str, updated_at: datetime):
            self.id = order_id
            self.run_id = None
            self.status = status
            self.symbol = "AAA"
            self.side = side
            self.quantity = 1.0
            self.filled_quantity = 1.0
            self.updated_at = updated_at
            self.params = {"mode": "paper"}

    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def all(self):
            return list(self._rows)

    class _FakeSession:
        def __init__(self, batches):
            self._batches = iter(batches)

        def query(self, *_args, **_kwargs):
            return _FakeQuery(next(self._batches))

    recent_terminal_fill = _FakeOrder(
        order_id=1001,
        status="FILLED",
        side="BUY",
        updated_at=datetime(2026, 2, 12, 19, 19, 0),
    )
    session = _FakeSession(
        [
            [recent_terminal_fill],
            [recent_terminal_fill],
        ]
    )

    monkeypatch.setattr(
        ib_account_module,
        "_load_direct_order_baseline_qty",
        lambda **_kwargs: 0.0,
    )

    inconsistent = ib_account_module._is_positions_snapshot_inconsistent_with_recent_fills(
        session,
        mode="paper",
        refreshed_at="2026-02-12T19:21:00Z",
        items=[{"symbol": "AAA", "quantity": 0.0}],
    )
    assert inconsistent is False


def test_inconsistent_check_keeps_recent_terminal_fill_overlay_window(monkeypatch):
    from datetime import datetime
    from app.services import ib_account as ib_account_module

    class _FakeOrder:
        def __init__(self, *, order_id: int, status: str, side: str, updated_at: datetime):
            self.id = order_id
            self.run_id = None
            self.status = status
            self.symbol = "AAA"
            self.side = side
            self.quantity = 1.0
            self.filled_quantity = 1.0
            self.updated_at = updated_at
            self.params = {"mode": "paper"}

    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def all(self):
            return list(self._rows)

    class _FakeSession:
        def __init__(self, batches):
            self._batches = iter(batches)

        def query(self, *_args, **_kwargs):
            return _FakeQuery(next(self._batches))

    very_recent_terminal_fill = _FakeOrder(
        order_id=1001,
        status="FILLED",
        side="BUY",
        updated_at=datetime(2026, 2, 12, 19, 20, 45),
    )
    session = _FakeSession(
        [
            [very_recent_terminal_fill],
            [very_recent_terminal_fill],
        ]
    )

    monkeypatch.setattr(
        ib_account_module,
        "_load_direct_order_baseline_qty",
        lambda **_kwargs: 0.0,
    )

    inconsistent = ib_account_module._is_positions_snapshot_inconsistent_with_recent_fills(
        session,
        mode="paper",
        refreshed_at="2026-02-12T19:21:00Z",
        items=[{"symbol": "AAA", "quantity": 0.0}],
    )
    assert inconsistent is True


def test_inconsistent_check_detects_fill_newer_than_positions_snapshot(monkeypatch):
    from datetime import datetime
    from app.services import ib_account as ib_account_module

    class _FakeOrder:
        def __init__(self, *, order_id: int, status: str, side: str, updated_at: datetime):
            self.id = order_id
            self.run_id = None
            self.status = status
            self.symbol = "AAA"
            self.side = side
            self.quantity = 1.0
            self.filled_quantity = 1.0
            self.updated_at = updated_at
            self.params = {"mode": "paper"}

    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def all(self):
            return list(self._rows)

    class _FakeSession:
        def __init__(self, batches):
            self._batches = iter(batches)

        def query(self, *_args, **_kwargs):
            return _FakeQuery(next(self._batches))

    newer_fill = _FakeOrder(
        order_id=1001,
        status="FILLED",
        side="SELL",
        updated_at=datetime(2026, 2, 12, 19, 21, 20),
    )
    session = _FakeSession(
        [
            [newer_fill],
            [newer_fill],
        ]
    )

    monkeypatch.setattr(
        ib_account_module,
        "_load_direct_order_baseline_qty",
        lambda **_kwargs: 1.0,
    )

    inconsistent = ib_account_module._is_positions_snapshot_inconsistent_with_recent_fills(
        session,
        mode="paper",
        refreshed_at="2026-02-12T19:21:00Z",
        items=[{"symbol": "AAA", "quantity": 1.0}],
    )
    assert inconsistent is True


def test_infer_positions_ignores_direct_fill_when_newer_order_exists(monkeypatch):
    from datetime import datetime
    from app.services import ib_account as ib_account_module

    class _FakeOrder:
        def __init__(
            self,
            *,
            order_id: int,
            run_id: int | None,
            side: str,
            updated_at: datetime,
        ):
            self.id = order_id
            self.run_id = run_id
            self.status = "FILLED"
            self.symbol = "AAA"
            self.side = side
            self.quantity = 1.0
            self.filled_quantity = 1.0
            self.updated_at = updated_at
            self.params = {"mode": "paper"}
            self.avg_fill_price = 10.0
            self.limit_price = 10.0

    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def all(self):
            return list(self._rows)

    class _FakeSession:
        def __init__(self, batches):
            self._batches = iter(batches)

        def query(self, *_args, **_kwargs):
            return _FakeQuery(next(self._batches))

    direct_sell = _FakeOrder(
        order_id=1001,
        run_id=None,
        side="SELL",
        updated_at=datetime(2026, 2, 12, 19, 17, 34),
    )
    newer_run_buy = _FakeOrder(
        order_id=2001,
        run_id=1093,
        side="BUY",
        updated_at=datetime(2026, 2, 12, 19, 20, 0),
    )
    session = _FakeSession(
        [
            [direct_sell],
            [newer_run_buy, direct_sell],
        ]
    )

    monkeypatch.setattr(
        ib_account_module,
        "_load_direct_order_baseline_qty",
        lambda **_kwargs: 1.0,
    )

    inferred = ib_account_module._infer_positions_from_recent_direct_fills(
        session,
        mode="paper",
        include_flattened=True,
    )
    assert inferred == []


def test_infer_positions_skips_old_terminal_fill_without_active_order(monkeypatch):
    from datetime import datetime
    from app.services import ib_account as ib_account_module

    class _FakeOrder:
        def __init__(self, *, order_id: int, status: str, side: str, updated_at: datetime):
            self.id = order_id
            self.run_id = None
            self.status = status
            self.symbol = "AAA"
            self.side = side
            self.quantity = 1.0
            self.filled_quantity = 1.0
            self.updated_at = updated_at
            self.params = {"mode": "paper"}
            self.avg_fill_price = 10.0
            self.limit_price = 10.0

    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def all(self):
            return list(self._rows)

    class _FakeSession:
        def __init__(self, batches):
            self._batches = iter(batches)

        def query(self, *_args, **_kwargs):
            return _FakeQuery(next(self._batches))

    old_terminal_fill = _FakeOrder(
        order_id=1001,
        status="FILLED",
        side="BUY",
        updated_at=datetime(2026, 2, 12, 19, 19, 0),
    )
    session = _FakeSession(
        [
            [old_terminal_fill],
            [old_terminal_fill],
        ]
    )

    monkeypatch.setattr(
        ib_account_module,
        "_load_direct_order_baseline_qty",
        lambda **_kwargs: 0.0,
    )

    inferred = ib_account_module._infer_positions_from_recent_direct_fills(
        session,
        mode="paper",
        include_flattened=True,
    )
    assert inferred == []


def test_order_newer_prefers_event_time_over_updated_at():
    from datetime import datetime
    from app.services import ib_account as ib_account_module

    class _FakeOrder:
        def __init__(self, *, order_id: int, updated_at: datetime, event_time: str):
            self.id = order_id
            self.updated_at = updated_at
            self.params = {"event_time": event_time}

    direct_sell = _FakeOrder(
        order_id=2698,
        updated_at=datetime(2026, 2, 12, 19, 45, 0),
        event_time="2026-02-12T19:43:30Z",
    )
    older_event = _FakeOrder(
        order_id=2640,
        updated_at=datetime(2026, 2, 12, 19, 46, 0),
        event_time="2026-02-12T19:24:10Z",
    )

    # Even if updated_at is newer, stale status refreshes must not outrank newer execution events.
    assert ib_account_module._is_order_newer(older_event, direct_sell) is False


def test_ibapi_verified_cache_reuses_payload_across_snapshot_tokens_within_interval(monkeypatch):
    from app.services import ib_account as ib_account_module

    ib_account_module._clear_account_positions_response_cache()
    monkeypatch.setattr(
        ib_account_module,
        "_IBAPI_VERIFY_MIN_INTERVAL_SECONDS",
        30.0,
        raising=False,
    )

    calls = {"count": 0}

    def _fake_fallback(_session, *, mode, refreshed_at, timeout_seconds=6.0):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "items": [{"symbol": "OLD", "position": 1.0, "quantity": 1.0}],
                "refreshed_at": refreshed_at,
                "stale": False,
                "source_detail": "ib_holdings_ibapi_fallback",
            }
        return {
            "items": [{"symbol": "NEW", "position": 2.0, "quantity": 2.0}],
            "refreshed_at": refreshed_at,
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
        }

    monkeypatch.setattr(
        ib_account_module,
        "_load_positions_via_ibapi_fallback",
        _fake_fallback,
    )

    first = ib_account_module._load_positions_via_ibapi_verified(
        object(),
        mode="paper",
        refreshed_at="2026-02-13T17:23:30Z",
        force=False,
    )
    second = ib_account_module._load_positions_via_ibapi_verified(
        object(),
        mode="paper",
        refreshed_at="2026-02-13T17:23:31Z",
        force=False,
    )

    assert calls["count"] == 1
    assert first is not None and first["items"][0]["symbol"] == "OLD"
    assert second is not None and second["items"][0]["symbol"] == "OLD"


def test_ibapi_verified_uses_soft_timeout_for_non_force(monkeypatch):
    from app.services import ib_account as ib_account_module

    ib_account_module._clear_account_positions_response_cache()
    monkeypatch.setattr(
        ib_account_module,
        "_IBAPI_VERIFY_MIN_INTERVAL_SECONDS",
        0.0,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_IBAPI_VERIFY_TIMEOUT_SECONDS",
        1.5,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_IBAPI_VERIFY_SOFT_TIMEOUT_SECONDS",
        0.35,
        raising=False,
    )

    timeouts: list[float] = []

    def _fake_fallback(_session, *, mode, refreshed_at, timeout_seconds=6.0):
        timeouts.append(float(timeout_seconds))
        return {
            "items": [{"symbol": "AAA", "position": 1.0, "quantity": 1.0}],
            "refreshed_at": refreshed_at,
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
        }

    monkeypatch.setattr(
        ib_account_module,
        "_load_positions_via_ibapi_fallback",
        _fake_fallback,
    )

    _ = ib_account_module._load_positions_via_ibapi_verified(
        object(),
        mode="paper",
        refreshed_at="2026-02-13T17:23:30Z",
        force=False,
    )
    _ = ib_account_module._load_positions_via_ibapi_verified(
        object(),
        mode="paper",
        refreshed_at="2026-02-13T17:23:31Z",
        force=True,
    )

    assert len(timeouts) == 2
    assert abs(timeouts[0] - 0.35) < 1e-9
    assert abs(timeouts[1] - 1.5) < 1e-9


def test_load_positions_via_ibapi_fallback_prefers_reused_session(monkeypatch):
    from app.services import ib_account as ib_account_module

    class _Settings:
        host = "127.0.0.1"
        port = 4002
        account_id = None

    class _SharedSession:
        def __init__(self):
            self.calls = 0

        def fetch_positions(self, *, timeout_seconds: float):
            self.calls += 1
            return [
                {
                    "symbol": "AAPL",
                    "position": 3.0,
                    "quantity": 3.0,
                    "avg_cost": 189.2,
                }
            ]

    shared = _SharedSession()
    monkeypatch.setattr(
        ib_account_module,
        "get_or_create_ib_settings",
        lambda _session: _Settings(),
    )
    monkeypatch.setattr(
        ib_account_module,
        "get_ib_read_session",
        lambda *, mode, host, port, client_id_hint=None: shared,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_fetch_positions_via_ibapi",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("transient_fetch_positions_should_not_run")),
        raising=False,
    )

    payload = ib_account_module._load_positions_via_ibapi_fallback(
        object(),
        mode="paper",
        refreshed_at="2026-02-20T22:16:00Z",
        timeout_seconds=0.5,
    )
    assert payload is not None
    assert payload["source_detail"] == "ib_holdings_ibapi_fallback"
    assert payload["items"][0]["symbol"] == "AAPL"
    assert shared.calls == 1


def test_load_positions_via_ibapi_fallback_respects_transient_circuit(monkeypatch):
    from app.services import ib_account as ib_account_module

    class _Settings:
        host = "127.0.0.1"
        port = 4002
        account_id = None

    monkeypatch.setattr(
        ib_account_module,
        "get_or_create_ib_settings",
        lambda _session: _Settings(),
    )
    monkeypatch.setattr(
        ib_account_module,
        "get_ib_read_session",
        lambda *, mode, host, port, client_id_hint=None: None,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "can_attempt_ib_transient_fallback",
        lambda *, mode, host, port, purpose: False,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_fetch_positions_via_ibapi",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("transient_probe_should_be_blocked")),
        raising=False,
    )

    payload = ib_account_module._load_positions_via_ibapi_fallback(
        object(),
        mode="paper",
        refreshed_at="2026-02-20T22:16:00Z",
        timeout_seconds=0.5,
    )
    assert payload is None


def test_load_positions_via_ibapi_fallback_uses_stable_transient_client_id(monkeypatch):
    from app.services import ib_account as ib_account_module

    class _Settings:
        host = "127.0.0.1"
        port = 4002
        account_id = None

    tracker = {"client_id": None, "recorded_success": None}

    monkeypatch.setattr(
        ib_account_module,
        "get_or_create_ib_settings",
        lambda _session: _Settings(),
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "get_ib_read_session",
        lambda *, mode, host, port, client_id_hint=None: None,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "can_attempt_ib_transient_fallback",
        lambda *, mode, host, port, purpose: True,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "resolve_ib_transient_client_id",
        lambda *, mode, purpose: 180001102,
        raising=False,
    )

    def _fake_fetch(*, host: str, port: int, client_id: int, timeout_seconds: float):
        tracker["client_id"] = int(client_id)
        return []

    monkeypatch.setattr(
        ib_account_module,
        "_fetch_positions_via_ibapi",
        _fake_fetch,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "record_ib_transient_fallback_result",
        lambda *, mode, host, port, purpose, success: tracker.__setitem__("recorded_success", bool(success)),
        raising=False,
    )

    payload = ib_account_module._load_positions_via_ibapi_fallback(
        object(),
        mode="paper",
        refreshed_at="2026-02-20T22:16:00Z",
        timeout_seconds=0.5,
    )
    assert payload is not None
    assert tracker["client_id"] == 180001102
    assert tracker["recorded_success"] is True
