from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sys

from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeRun
from app.routes import trade as trade_routes
from app.services.trade_orders import create_trade_order


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_orders_total_count_header():
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    trade_routes.get_session = _get_session  # type: ignore[attr-defined]

    create_trade_order(
        session,
        {
            "client_order_id": "manual-1",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
            "params": {"client_order_id_auto": True},
        },
    )
    session.commit()

    response = Response()
    result = trade_routes.list_trade_orders(limit=1, offset=0, run_id=None, response=response)
    assert response.headers.get("X-Total-Count") == "1"
    assert len(result) == 1

    session.close()


def test_orders_sorted_by_id_desc():
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    trade_routes.get_session = _get_session  # type: ignore[attr-defined]

    create_trade_order(
        session,
        {
            "client_order_id": "manual-1",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
            "params": {"client_order_id_auto": True},
        },
    )
    create_trade_order(
        session,
        {
            "client_order_id": "manual-2",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
            "params": {"client_order_id_auto": True},
        },
    )
    session.commit()

    response = Response()
    result = trade_routes.list_trade_orders(limit=20, offset=0, run_id=None, response=response)
    ids = [item.id for item in result]
    assert ids == sorted(ids, reverse=True)

    session.close()


def test_orders_manual_sync_enables_include_new(monkeypatch):
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(trade_routes, "get_session", _get_session)

    create_trade_order(
        session,
        {
            "client_order_id": "manual-new-1",
            "symbol": "NVDA",
            "side": "SELL",
            "quantity": 1,
            "order_type": "ADAPTIVE_LMT",
            "status": "NEW",
            "params": {"event_tag": "direct:manual-new-1", "mode": "paper"},
        },
    )
    session.commit()

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    monkeypatch.setattr(trade_routes, "resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(trade_routes, "ingest_execution_events", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        trade_routes,
        "reconcile_direct_submit_command_results",
        lambda *_args, **_kwargs: 0,
    )
    monkeypatch.setattr(
        trade_routes,
        "reconcile_cancel_requested_orders",
        lambda *_args, **_kwargs: {"updated": 0},
    )
    monkeypatch.setattr(
        trade_routes,
        "read_open_orders",
        lambda _root: {
            "items": [],
            "stale": False,
            "source_detail": "ib_open_orders_empty",
            "bridge_client_id": 0,
            "refreshed_at": now_iso,
        },
    )
    monkeypatch.setattr(
        trade_routes,
        "read_positions",
        lambda _root: {
            "items": [],
            "stale": False,
            "source_detail": "ib_holdings_empty",
            "refreshed_at": now_iso,
        },
    )
    monkeypatch.setattr(trade_routes, "ensure_positions_baseline", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        trade_routes,
        "compute_realized_pnl",
        lambda *_args, **_kwargs: type("Realized", (), {"order_totals": {}})(),
    )
    monkeypatch.setattr(
        trade_routes.trade_executor,
        "reconcile_direct_orders_with_positions",
        lambda *_args, **_kwargs: {
            "checked": 0,
            "reconciled": 0,
            "skipped": 0,
            "terminalized_no_fill_timeout": 0,
        },
    )
    monkeypatch.setattr(
        trade_routes.trade_executor,
        "reconcile_run_with_positions",
        lambda *_args, **_kwargs: {"checked": 0, "reconciled": 0, "skipped": 0},
    )

    calls: list[dict] = []
    reconcile_calls = {"direct_submit": 0, "cancel": 0, "ingest": 0}

    def _spy_sync(_session, _payload, **kwargs):
        calls.append(dict(kwargs))
        return {"updated": 0, "skipped": 0}

    def _spy_reconcile_direct(*_args, **_kwargs):
        reconcile_calls["direct_submit"] += 1
        return 0

    def _spy_reconcile_cancel(*_args, **_kwargs):
        reconcile_calls["cancel"] += 1
        return {"updated": 0}

    def _spy_ingest(*_args, **_kwargs):
        reconcile_calls["ingest"] += 1
        return {"processed": 0}

    monkeypatch.setattr(trade_routes, "sync_trade_orders_from_open_orders", _spy_sync)
    monkeypatch.setattr(trade_routes, "reconcile_direct_submit_command_results", _spy_reconcile_direct)
    monkeypatch.setattr(trade_routes, "reconcile_cancel_requested_orders", _spy_reconcile_cancel)
    monkeypatch.setattr(trade_routes, "ingest_execution_events", _spy_ingest)

    response = Response()
    trade_routes.list_trade_orders(limit=20, offset=0, run_id=None, response=response)

    assert calls == []
    assert reconcile_calls == {"direct_submit": 0, "cancel": 0, "ingest": 0}

    session.close()


def test_orders_light_sync_skips_run_scoped_open_orders_when_deep_sync_not_due(monkeypatch):
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(trade_routes, "get_session", _get_session)

    run = TradeRun(
        project_id=1,
        decision_snapshot_id=1,
        mode="paper",
        status="running",
        params={"lean_execution": {"output_dir": "/tmp/non-existent"}},
    )
    session.add(run)
    session.commit()

    create_trade_order(
        session,
        {
            "client_order_id": "oi_run_1",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
            "status": "SUBMITTED",
            "params": {"event_tag": "oi_1_1", "mode": "paper"},
        },
        run_id=run.id,
    )
    session.commit()

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    monkeypatch.setattr(trade_routes, "_should_run_trade_orders_deep_sync", lambda _now_mono: False)
    monkeypatch.setattr(trade_routes, "resolve_bridge_root", lambda: Path("/tmp"))
    monkeypatch.setattr(trade_routes, "ingest_execution_events", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        trade_routes,
        "reconcile_direct_submit_command_results",
        lambda *_args, **_kwargs: 0,
    )
    monkeypatch.setattr(
        trade_routes,
        "reconcile_cancel_requested_orders",
        lambda *_args, **_kwargs: {"updated": 0},
    )
    monkeypatch.setattr(
        trade_routes,
        "read_open_orders",
        lambda _root: {
            "items": [],
            "stale": False,
            "source_detail": "ib_open_orders_empty",
            "bridge_client_id": 0,
            "refreshed_at": now_iso,
        },
    )
    monkeypatch.setattr(
        trade_routes,
        "read_positions",
        lambda _root: {
            "items": [],
            "stale": False,
            "source_detail": "ib_holdings_empty",
            "refreshed_at": now_iso,
        },
    )
    monkeypatch.setattr(trade_routes, "ensure_positions_baseline", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        trade_routes,
        "compute_realized_pnl",
        lambda *_args, **_kwargs: type("Realized", (), {"order_totals": {}})(),
    )
    monkeypatch.setattr(
        trade_routes.trade_executor,
        "reconcile_direct_orders_with_positions",
        lambda *_args, **_kwargs: {
            "checked": 0,
            "reconciled": 0,
            "skipped": 0,
            "terminalized_no_fill_timeout": 0,
        },
    )
    monkeypatch.setattr(
        trade_routes.trade_executor,
        "reconcile_run_with_positions",
        lambda *_args, **_kwargs: {"checked": 0, "reconciled": 0, "skipped": 0},
    )

    calls: list[dict] = []

    def _spy_sync(_session, _payload, **kwargs):
        calls.append(dict(kwargs))
        return {"updated": 0, "skipped": 0}

    monkeypatch.setattr(trade_routes, "sync_trade_orders_from_open_orders", _spy_sync)

    response = Response()
    trade_routes.list_trade_orders(limit=20, offset=0, run_id=None, response=response)

    assert calls == []

    session.close()


def test_orders_short_ttl_cache_reuses_recent_result(monkeypatch):
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(trade_routes, "get_session", _get_session)
    monkeypatch.setattr(trade_routes, "_TRADE_ORDERS_RESPONSE_CACHE_TTL_SECONDS", 1.0, raising=False)
    trade_routes._clear_trade_orders_response_cache()

    create_trade_order(
        session,
        {
            "client_order_id": "cache-1",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
            "params": {"client_order_id_auto": True},
        },
    )
    session.commit()

    calls = {"settings": 0}
    original_get_settings = trade_routes.get_or_create_ib_settings

    def _spy_get_settings(*args, **kwargs):
        calls["settings"] += 1
        return original_get_settings(*args, **kwargs)

    monkeypatch.setattr(trade_routes, "get_or_create_ib_settings", _spy_get_settings)

    response = Response()
    first = trade_routes.list_trade_orders(limit=20, offset=0, run_id=None, response=response)
    second = trade_routes.list_trade_orders(limit=20, offset=0, run_id=None, response=response)

    assert len(first) == 1
    assert len(second) == 1
    assert calls["settings"] == 1
    trade_routes._clear_trade_orders_response_cache()

    session.close()


def test_orders_run_scoped_query_does_not_ingest_events_in_request_path(monkeypatch, tmp_path):
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(trade_routes, "get_session", _get_session)

    run = TradeRun(
        project_id=1,
        decision_snapshot_id=1,
        mode="paper",
        status="running",
        params={},
    )
    session.add(run)
    session.commit()

    create_trade_order(
        session,
        {
            "client_order_id": "oi_run_1",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
            "status": "SUBMITTED",
            "params": {"event_tag": "oi_1_1", "mode": "paper"},
        },
        run_id=run.id,
    )
    session.commit()

    bridge_root = tmp_path / "bridge"
    bridge_root.mkdir(parents=True, exist_ok=True)
    (bridge_root / "execution_events.jsonl").write_text(
        '{"tag":"oi_1_1","status":"Submitted","time":"2026-02-13T00:00:00Z"}\n',
        encoding="utf-8",
    )
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    monkeypatch.setattr(trade_routes, "resolve_bridge_root", lambda: bridge_root)
    monkeypatch.setattr(
        trade_routes,
        "read_open_orders",
        lambda _root: {
            "items": [],
            "stale": False,
            "source_detail": "ib_open_orders_empty",
            "bridge_client_id": 0,
            "refreshed_at": now_iso,
        },
    )
    monkeypatch.setattr(
        trade_routes,
        "read_positions",
        lambda _root: {
            "items": [],
            "stale": False,
            "source_detail": "ib_holdings_empty",
            "refreshed_at": now_iso,
        },
    )
    monkeypatch.setattr(trade_routes, "ensure_positions_baseline", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        trade_routes,
        "compute_realized_pnl",
        lambda *_args, **_kwargs: type("Realized", (), {"order_totals": {}})(),
    )
    monkeypatch.setattr(
        trade_routes.trade_executor,
        "reconcile_direct_orders_with_positions",
        lambda *_args, **_kwargs: {
            "checked": 0,
            "reconciled": 0,
            "skipped": 0,
            "terminalized_no_fill_timeout": 0,
        },
    )
    monkeypatch.setattr(
        trade_routes.trade_executor,
        "reconcile_run_with_positions",
        lambda *_args, **_kwargs: {"checked": 0, "reconciled": 0, "skipped": 0},
    )

    ingest_calls: list[dict] = []

    def _spy_ingest(_path, **kwargs):
        ingest_calls.append(dict(kwargs))
        return {"processed": 0}

    monkeypatch.setattr(trade_routes, "ingest_execution_events", _spy_ingest)

    response = Response()
    trade_routes.list_trade_orders(limit=20, offset=0, run_id=run.id, response=response)

    # Root-cause fix: run-scoped orders query is read-only and must not trigger
    # execution-event ingestion or reconciliation in request path.
    assert ingest_calls == []

    session.close()
