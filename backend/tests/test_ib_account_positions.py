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
    assert calls["ensure"] == 1
    assert payload["items"][0]["symbol"] == "AAA"
    assert payload["items"][0]["position"] == 2
    assert payload["stale"] is True


def test_ib_account_positions_overlays_non_stale_ib_holdings_when_inconsistent(monkeypatch):
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
        "_infer_positions_from_recent_direct_fills",
        lambda *_args, **_kwargs: [
            {
                "symbol": "AAA",
                "position": 1.0,
                "quantity": 1.0,
                "avg_cost": 11.0,
            }
        ],
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
    assert calls["ensure"] == 1
    assert payload["items"][0]["symbol"] == "AAA"
    assert payload["items"][0]["position"] == 1.0
    assert payload["stale"] is True
    assert payload["source_detail"] == "ib_holdings_overlay_recent_fills"


def test_ib_account_positions_overlay_can_remove_flattened_symbol(monkeypatch):
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
        "_infer_positions_from_recent_direct_fills",
        lambda *_args, **_kwargs: [
            {
                "symbol": "AAA",
                "position": 0.0,
                "quantity": 0.0,
                "avg_cost": 11.0,
            }
        ],
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
    assert calls["ensure"] == 1
    assert payload["source_detail"] == "ib_holdings_overlay_recent_fills"
    assert payload["stale"] is True
    assert payload["items"] == []


def test_ib_account_positions_infers_from_recent_direct_fills_when_snapshot_stale(monkeypatch):
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
        lambda _session, *, mode: [
            {
                "symbol": "AAPL",
                "position": 1.0,
                "quantity": 1.0,
                "avg_cost": 271.1,
            }
        ],
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
    assert payload["source_detail"] == "ib_holdings_inferred_recent_fills"
    assert payload["items"][0]["symbol"] == "AAPL"
    assert payload["items"][0]["position"] == 1.0
    assert payload["items"][0]["market_price"] == 272.0
    assert payload["items"][0]["market_value"] == 272.0


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
