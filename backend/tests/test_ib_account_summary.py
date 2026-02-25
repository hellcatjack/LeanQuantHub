from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_filter_summary_whitelist():
    from app.services.ib_account import _filter_summary

    raw = {"NetLiquidation": "100", "Foo": "bar"}
    core = _filter_summary(raw, full=False)
    assert "NetLiquidation" in core
    assert "Foo" not in core
    full = _filter_summary(raw, full=True)
    assert "Foo" in full


def test_build_summary_tags_uses_core_tags():
    from app.services.ib_account import CORE_TAGS, build_account_summary_tags

    tags = build_account_summary_tags(full=False)
    parts = {item.strip() for item in tags.split(",") if item.strip()}
    assert "All" not in parts
    for tag in CORE_TAGS:
        assert tag in parts


def test_resolve_ib_account_settings_skips_probe(monkeypatch):
    from app.services import ib_account as ib_account_module

    sentinel = object()
    monkeypatch.setattr(ib_account_module, "get_or_create_ib_settings", lambda _session: sentinel)
    monkeypatch.setattr(ib_account_module, "ensure_ib_client_id", lambda _session: (_ for _ in ()).throw(RuntimeError("probe-called")))

    assert ib_account_module.resolve_ib_account_settings(object()) is sentinel


def test_iter_account_client_ids_defaults():
    from app.services.ib_account import iter_account_client_ids

    assert list(iter_account_client_ids(100, attempts=3)) == [100, 101, 102]


def test_get_account_summary_merges_ibapi_when_realized_pnl_missing(monkeypatch):
    from app.services import ib_account as ib_account_module

    class _DummySession:
        def query(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(ib_account_module, "CACHE_ROOT", None, raising=False)
    monkeypatch.setattr(
        ib_account_module,
        "read_account_summary",
        lambda _root: {
            "items": {
                "NetLiquidation": "1000",
                "UnrealizedPnL": "20",
                "__by_currency__": {"NetLiquidation": {"USD": "1000"}},
            },
            "updated_at": "2026-02-17T00:00:00Z",
            "stale": False,
            "source": "lean_bridge",
        },
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_account_summary_via_ibapi_verified",
        lambda _session, *, mode, refreshed_at, force=False, timeout_seconds=None: {
            "items": {
                "RealizedPnL": "5",
                "__by_currency__": {
                    "RealizedPnL": {"USD": "5"},
                    "UnrealizedPnL": {"USD": "20"},
                },
            },
            "source": "ibapi",
            "stale": False,
        },
        raising=False,
    )

    payload = ib_account_module.get_account_summary(_DummySession(), mode="paper", full=True, force_refresh=False)
    items = payload.get("items") if isinstance(payload.get("items"), dict) else {}
    by_currency = items.get("__by_currency__") if isinstance(items.get("__by_currency__"), dict) else {}

    assert items.get("RealizedPnL") == "5"
    assert by_currency.get("RealizedPnL") == {"USD": "5"}
    assert by_currency.get("NetLiquidation") == {"USD": "1000"}


def test_get_account_summary_skips_ibapi_when_summary_fields_are_complete(monkeypatch):
    from app.services import ib_account as ib_account_module

    class _DummySession:
        def query(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(ib_account_module, "CACHE_ROOT", None, raising=False)
    monkeypatch.setattr(
        ib_account_module,
        "read_account_summary",
        lambda _root: {
            "items": {
                "NetLiquidation": "1000",
                "UnrealizedPnL": "20",
                "RealizedPnL": "8",
                "__by_currency__": {
                    "NetLiquidation": {"USD": "1000"},
                    "UnrealizedPnL": {"USD": "20"},
                    "RealizedPnL": {"USD": "8"},
                },
            },
            "updated_at": "2026-02-17T00:00:00Z",
            "stale": False,
            "source": "lean_bridge",
        },
        raising=False,
    )

    marker = {"called": False}

    def _unexpected(*_args, **_kwargs):
        marker["called"] = True
        return None

    monkeypatch.setattr(
        ib_account_module,
        "_load_account_summary_via_ibapi_verified",
        _unexpected,
        raising=False,
    )

    payload = ib_account_module.get_account_summary(_DummySession(), mode="paper", full=True, force_refresh=False)
    assert payload.get("items", {}).get("RealizedPnL") == "8"
    assert marker["called"] is False


def test_get_account_summary_backfills_pnl_from_ibapi_pnl_stream(monkeypatch):
    from app.services import ib_account as ib_account_module

    class _DummySession:
        def query(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(ib_account_module, "CACHE_ROOT", None, raising=False)
    monkeypatch.setattr(
        ib_account_module,
        "read_account_summary",
        lambda _root: {
            "items": {
                "NetLiquidation": "1000",
                "__by_currency__": {"NetLiquidation": {"USD": "1000"}},
            },
            "updated_at": "2026-02-17T00:00:00Z",
            "stale": False,
            "source": "lean_bridge",
        },
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_account_summary_via_ibapi_verified",
        lambda _session, *, mode, refreshed_at, force=False, timeout_seconds=None: {
            "items": {"NetLiquidation": "1000"},
            "source": "ibapi",
            "stale": False,
        },
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_account_pnl_via_ibapi_verified",
        lambda _session, *, mode, refreshed_at, force=False: {
            "RealizedPnL": 12.5,
            "UnrealizedPnL": -3.25,
        },
        raising=False,
    )

    payload = ib_account_module.get_account_summary(_DummySession(), mode="paper", full=True, force_refresh=False)
    items = payload.get("items") if isinstance(payload.get("items"), dict) else {}
    assert items.get("RealizedPnL") == 12.5
    assert items.get("UnrealizedPnL") == -3.25


def test_get_account_summary_non_full_uses_ibapi_when_bridge_summary_missing(monkeypatch):
    from app.services import ib_account as ib_account_module

    class _DummySession:
        def query(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(ib_account_module, "CACHE_ROOT", None, raising=False)
    monkeypatch.setattr(
        ib_account_module,
        "read_account_summary",
        lambda _root: {
            "items": {},
            "updated_at": "2026-02-18T10:18:47Z",
            "stale": True,
            "source": "lean_bridge",
        },
        raising=False,
    )

    called = {"count": 0}

    def _fake_ibapi(_session, *, mode, refreshed_at, force=False, timeout_seconds=None):
        called["count"] += 1
        return {
            "items": {
                "NetLiquidation": "1234.56",
                "TotalCashValue": "345.67",
                "AvailableFunds": "999.99",
            },
            "source": "ibapi",
            "stale": False,
            "refreshed_at": refreshed_at,
        }

    monkeypatch.setattr(
        ib_account_module,
        "_load_account_summary_via_ibapi_verified",
        _fake_ibapi,
        raising=False,
    )

    payload = ib_account_module.get_account_summary(_DummySession(), mode="paper", full=False, force_refresh=False)

    assert called["count"] == 1
    items = payload.get("items") if isinstance(payload.get("items"), dict) else {}
    assert items.get("NetLiquidation") == "1234.56"
    assert payload.get("stale") is False


def test_get_account_summary_non_full_uses_short_probe_timeout_for_ib_account_empty(monkeypatch):
    from app.services import ib_account as ib_account_module

    class _DummySession:
        def query(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(ib_account_module, "CACHE_ROOT", None, raising=False)
    monkeypatch.setattr(
        ib_account_module,
        "read_account_summary",
        lambda _root: {
            "items": {},
            "updated_at": "2026-02-18T10:18:47Z",
            "stale": True,
            "source": "lean_bridge",
            "source_detail": "ib_account_empty",
        },
        raising=False,
    )

    captured: dict[str, object] = {}

    def _fake_ibapi(_session, *, mode, refreshed_at, force=False, timeout_seconds=None):
        captured["timeout_seconds"] = timeout_seconds
        return None

    monkeypatch.setattr(
        ib_account_module,
        "_load_account_summary_via_ibapi_verified",
        _fake_ibapi,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_build_account_summary_from_positions_snapshot",
        lambda *, mode: {
            "items": {"NetLiquidation": 1200.0},
            "stale": True,
            "refreshed_at": "2026-02-18T10:15:26Z",
        },
        raising=False,
    )

    payload = ib_account_module.get_account_summary(_DummySession(), mode="paper", full=False, force_refresh=False)
    assert float(captured.get("timeout_seconds") or 0.0) <= 0.35
    assert payload.get("items", {}).get("NetLiquidation") == 1200.0


def test_get_account_summary_derives_from_positions_when_ibapi_unavailable(monkeypatch):
    from app.services import ib_account as ib_account_module

    class _DummySession:
        def query(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(ib_account_module, "CACHE_ROOT", None, raising=False)
    monkeypatch.setattr(
        ib_account_module,
        "read_account_summary",
        lambda _root: {
            "items": {},
            "updated_at": "2026-02-18T10:18:47Z",
            "stale": True,
            "source": "lean_bridge",
            "source_detail": "ib_account_empty",
        },
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_account_summary_via_ibapi_verified",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_build_account_summary_from_positions_snapshot",
        lambda *, mode: {
            "items": {
                "NetLiquidation": 24036.9,
                "GrossPositionValue": 24036.9,
                "UnrealizedPnL": 135.7,
            },
            "refreshed_at": "2026-02-18T10:15:26Z",
            "stale": True,
            "source": "derived_positions",
        },
        raising=False,
    )

    payload = ib_account_module.get_account_summary(_DummySession(), mode="paper", full=False, force_refresh=False)
    items = payload.get("items") if isinstance(payload.get("items"), dict) else {}
    assert items.get("NetLiquidation") == 24036.9
    assert items.get("GrossPositionValue") == 24036.9
    assert payload.get("stale") is True
    assert "derived_positions" in str(payload.get("source") or "")


def test_get_account_summary_prefers_guard_equity_when_positions_only_netliq(monkeypatch):
    from app.services import ib_account as ib_account_module

    class _DummySession:
        def query(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(ib_account_module, "CACHE_ROOT", None, raising=False)
    monkeypatch.setattr(
        ib_account_module,
        "read_account_summary",
        lambda _root: {
            "items": {},
            "updated_at": "2026-02-18T10:18:47Z",
            "stale": True,
            "source": "lean_bridge",
            "source_detail": "ib_account_empty",
        },
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_account_summary_via_ibapi_verified",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_build_account_summary_from_positions_snapshot",
        lambda *, mode: {
            "items": {
                "NetLiquidation": 24036.9,
                "GrossPositionValue": 24036.9,
                "UnrealizedPnL": -50.6,
            },
            "refreshed_at": "2026-02-18T10:15:26Z",
            "stale": True,
            "source": "derived_positions",
        },
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_load_guard_equity_proxy",
        lambda _session, *, mode: 29299.1,
        raising=False,
    )

    payload = ib_account_module.get_account_summary(_DummySession(), mode="paper", full=False, force_refresh=False)
    items = payload.get("items") if isinstance(payload.get("items"), dict) else {}
    assert items.get("NetLiquidation") == 29299.1
    assert items.get("EquityWithLoanValue") == 29299.1
    assert items.get("GrossPositionValue") == 24036.9
    assert "guard_equity" in str(payload.get("source") or "")


def test_ibapi_summary_verified_cache_reuses_payload_across_snapshot_tokens(monkeypatch):
    from app.services import ib_account as ib_account_module

    ib_account_module._clear_account_positions_response_cache()
    monkeypatch.setattr(
        ib_account_module,
        "_IBAPI_SUMMARY_VERIFY_MIN_INTERVAL_SECONDS",
        30.0,
        raising=False,
    )

    calls = {"count": 0}

    def _fake_fallback(_session, *, mode, refreshed_at, timeout_seconds=6.0):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "items": {"NetLiquidation": "1000"},
                "source": "ibapi",
                "stale": False,
            }
        return {
            "items": {"NetLiquidation": "2000"},
            "source": "ibapi",
            "stale": False,
        }

    monkeypatch.setattr(
        ib_account_module,
        "_load_account_summary_via_ibapi_fallback",
        _fake_fallback,
        raising=False,
    )

    first = ib_account_module._load_account_summary_via_ibapi_verified(
        object(),
        mode="paper",
        refreshed_at="2026-02-13T17:23:30Z",
        force=False,
    )
    second = ib_account_module._load_account_summary_via_ibapi_verified(
        object(),
        mode="paper",
        refreshed_at="2026-02-13T17:23:31Z",
        force=False,
    )

    assert calls["count"] == 1
    assert first is not None and first.get("items", {}).get("NetLiquidation") == "1000"
    assert second is not None and second.get("items", {}).get("NetLiquidation") == "1000"


def test_ibapi_pnl_verified_cache_reuses_payload_across_snapshot_tokens(monkeypatch):
    from app.services import ib_account as ib_account_module

    ib_account_module._clear_account_positions_response_cache()
    monkeypatch.setattr(
        ib_account_module,
        "_IBAPI_PNL_VERIFY_MIN_INTERVAL_SECONDS",
        30.0,
        raising=False,
    )

    calls = {"count": 0}

    def _fake_fallback(_session, *, mode, refreshed_at, timeout_seconds=6.0):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"RealizedPnL": 1.0, "UnrealizedPnL": 2.0}
        return {"RealizedPnL": 3.0, "UnrealizedPnL": 4.0}

    monkeypatch.setattr(
        ib_account_module,
        "_load_account_pnl_via_ibapi_fallback",
        _fake_fallback,
        raising=False,
    )

    first = ib_account_module._load_account_pnl_via_ibapi_verified(
        object(),
        mode="paper",
        refreshed_at="2026-02-13T17:23:30Z",
        force=False,
    )
    second = ib_account_module._load_account_pnl_via_ibapi_verified(
        object(),
        mode="paper",
        refreshed_at="2026-02-13T17:23:31Z",
        force=False,
    )

    assert calls["count"] == 1
    assert first is not None and first.get("RealizedPnL") == 1.0
    assert second is not None and second.get("RealizedPnL") == 1.0


def test_load_account_summary_via_ibapi_fallback_prefers_reused_session(monkeypatch):
    from app.services import ib_account as ib_account_module

    class _Settings:
        host = "127.0.0.1"
        port = 4002
        account_id = "DU1234567"

    class _SharedSession:
        def __init__(self):
            self.calls = 0

        def fetch_account_summary(self, *, tags: tuple[str, ...], account_id: str | None, timeout_seconds: float):
            self.calls += 1
            assert "NetLiquidation" in set(tags)
            assert account_id == "DU1234567"
            return [
                {
                    "name": "NetLiquidation",
                    "value": "12345.67",
                    "currency": "USD",
                    "account": "DU1234567",
                }
            ]

    shared = _SharedSession()
    monkeypatch.setattr(
        ib_account_module,
        "get_or_create_ib_settings",
        lambda _session: _Settings(),
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "get_ib_read_session",
        lambda *, mode, host, port, client_id_hint=None: shared,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_fetch_account_summary_via_ibapi",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("transient_fetch_summary_should_not_run")),
        raising=False,
    )

    payload = ib_account_module._load_account_summary_via_ibapi_fallback(
        object(),
        mode="paper",
        refreshed_at="2026-02-20T22:16:00Z",
        timeout_seconds=0.5,
    )
    assert payload is not None
    assert payload.get("items", {}).get("NetLiquidation") == "12345.67"
    assert shared.calls == 1


def test_load_account_pnl_via_ibapi_fallback_prefers_reused_session(monkeypatch):
    from app.services import ib_account as ib_account_module

    class _Settings:
        host = "127.0.0.1"
        port = 4002
        account_id = "DU7654321"

    class _SharedSession:
        def __init__(self):
            self.calls = 0

        def fetch_account_pnl(self, *, account_id: str, timeout_seconds: float):
            self.calls += 1
            assert account_id == "DU7654321"
            return {
                "RealizedPnL": 12.3,
                "UnrealizedPnL": -4.5,
                "DailyPnL": 7.8,
            }

    shared = _SharedSession()
    monkeypatch.setattr(
        ib_account_module,
        "get_or_create_ib_settings",
        lambda _session: _Settings(),
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "get_ib_read_session",
        lambda *, mode, host, port, client_id_hint=None: shared,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_fetch_account_pnl_via_ibapi",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("transient_fetch_pnl_should_not_run")),
        raising=False,
    )

    payload = ib_account_module._load_account_pnl_via_ibapi_fallback(
        object(),
        mode="paper",
        refreshed_at="2026-02-20T22:16:00Z",
        timeout_seconds=0.5,
    )
    assert payload is not None
    assert payload.get("RealizedPnL") == 12.3
    assert shared.calls == 1


def test_load_account_summary_via_ibapi_fallback_respects_transient_circuit(monkeypatch):
    from app.services import ib_account as ib_account_module

    class _Settings:
        host = "127.0.0.1"
        port = 4002
        account_id = "DU1234567"

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
        lambda *, mode, host, port, purpose: False,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "_fetch_account_summary_via_ibapi",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("transient_summary_probe_should_be_blocked")),
        raising=False,
    )

    payload = ib_account_module._load_account_summary_via_ibapi_fallback(
        object(),
        mode="paper",
        refreshed_at="2026-02-21T00:00:00Z",
        timeout_seconds=0.5,
    )
    assert payload is None


def test_load_account_pnl_via_ibapi_fallback_uses_stable_transient_client_id(monkeypatch):
    from app.services import ib_account as ib_account_module

    class _Settings:
        host = "127.0.0.1"
        port = 4002
        account_id = "DU7654321"

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
        lambda *, mode, purpose: 180001203,
        raising=False,
    )

    def _fake_fetch(*, host: str, port: int, client_id: int, timeout_seconds: float, account_id: str):
        tracker["client_id"] = int(client_id)
        return {"RealizedPnL": 1.0, "UnrealizedPnL": -1.0}

    monkeypatch.setattr(
        ib_account_module,
        "_fetch_account_pnl_via_ibapi",
        _fake_fetch,
        raising=False,
    )
    monkeypatch.setattr(
        ib_account_module,
        "record_ib_transient_fallback_result",
        lambda *, mode, host, port, purpose, success: tracker.__setitem__("recorded_success", bool(success)),
        raising=False,
    )

    payload = ib_account_module._load_account_pnl_via_ibapi_fallback(
        object(),
        mode="paper",
        refreshed_at="2026-02-21T00:00:00Z",
        timeout_seconds=0.5,
    )
    assert payload is not None
    assert payload.get("RealizedPnL") == 1.0
    assert tracker["client_id"] == 180001203
    assert tracker["recorded_success"] is True
