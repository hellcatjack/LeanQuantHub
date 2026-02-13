from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeOrder, TradeRun
from app.services.trade_execution_events_watchdog import (
    ingest_active_trade_order_events,
    reconcile_low_confidence_terminal_runs,
)
from app.services.trade_orders import create_trade_order, update_trade_order_status


def _make_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_ingest_active_trade_order_events_updates_direct_order(tmp_path):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        result = create_trade_order(
            session,
            {
                "client_order_id": "direct-watchdog-1",
                "symbol": "AAPL",
                "side": "BUY",
                "quantity": 1,
                "order_type": "MKT",
            },
        )
        session.commit()

        events_dir = tmp_path / f"direct_{result.order.id}"
        events_dir.mkdir(parents=True, exist_ok=True)
        (events_dir / "execution_events.jsonl").write_text(
            (
                '{"order_id":1,"symbol":"AAPL","status":"Submitted","filled":0.0,'
                '"fill_price":0.0,"direction":"Buy","time":"2026-02-11T16:50:00Z",'
                f'"tag":"direct:{result.order.id}"'
                '}\n'
                '{"order_id":1,"symbol":"AAPL","status":"Filled","filled":1.0,'
                '"fill_price":101.25,"direction":"Buy","time":"2026-02-11T16:50:01Z",'
                f'"tag":"direct:{result.order.id}"'
                '}\n'
            ),
            encoding="utf-8",
        )

        summary = ingest_active_trade_order_events(session, bridge_root=tmp_path, limit=20)
        session.expire_all()
        refreshed = session.query(TradeOrder).filter_by(id=result.order.id).one()

        assert summary["orders_scanned"] == 1
        assert summary["paths_ingested"] == 1
        assert refreshed.status == "FILLED"
        assert refreshed.filled_quantity == 1
        assert refreshed.avg_fill_price == 101.25
    finally:
        session.close()


def test_ingest_active_trade_order_events_prefers_recently_updated_rows(tmp_path):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        first = create_trade_order(
            session,
            {
                "client_order_id": "direct-watchdog-priority-1",
                "symbol": "AAPL",
                "side": "BUY",
                "quantity": 1,
                "order_type": "MKT",
            },
        ).order
        second = create_trade_order(
            session,
            {
                "client_order_id": "direct-watchdog-priority-2",
                "symbol": "MSFT",
                "side": "BUY",
                "quantity": 1,
                "order_type": "MKT",
            },
        ).order
        session.commit()

        update_trade_order_status(session, first, {"status": "SUBMITTED"})

        events_dir = tmp_path / f"direct_{first.id}"
        events_dir.mkdir(parents=True, exist_ok=True)
        (events_dir / "execution_events.jsonl").write_text(
            (
                '{"order_id":1,"symbol":"AAPL","status":"Submitted","filled":0.0,'
                '"fill_price":0.0,"direction":"Buy","time":"2026-02-11T16:55:00Z",'
                f'"tag":"direct:{first.id}"'
                '}\n'
                '{"order_id":1,"symbol":"AAPL","status":"Filled","filled":1.0,'
                '"fill_price":101.75,"direction":"Buy","time":"2026-02-11T16:55:01Z",'
                f'"tag":"direct:{first.id}"'
                '}\n'
            ),
            encoding="utf-8",
        )

        summary = ingest_active_trade_order_events(session, bridge_root=tmp_path, limit=1)
        session.expire_all()
        refreshed_first = session.query(TradeOrder).filter_by(id=first.id).one()
        refreshed_second = session.query(TradeOrder).filter_by(id=second.id).one()

        assert summary["orders_scanned"] == 1
        assert refreshed_first.status == "FILLED"
        assert refreshed_second.status == "NEW"
    finally:
        session.close()


def test_ingest_active_trade_order_events_ingests_leader_events(tmp_path):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        result = create_trade_order(
            session,
            {
                "client_order_id": "direct-watchdog-leader-1",
                "symbol": "AXON",
                "side": "BUY",
                "quantity": 1,
                "order_type": "ADAPTIVE_LMT",
            },
        )
        session.commit()

        (tmp_path / "execution_events.jsonl").write_text(
            (
                '{"order_id":11,"symbol":"AXON","status":"Submitted","filled":0.0,'
                '"fill_price":0.0,"direction":"Buy","time":"2026-02-11T16:53:52Z",'
                f'"tag":"direct:{result.order.id}","exec_id":"ib-submitted-1"'
                '}\n'
                '{"order_id":11,"symbol":"AXON","status":"Filled","filled":1.0,'
                '"fill_price":433.11,"direction":"Buy","time":"2026-02-11T16:54:12Z",'
                f'"tag":"direct:{result.order.id}","exec_id":"ib-fill-1"'
                '}\n'
            ),
            encoding="utf-8",
        )

        summary = ingest_active_trade_order_events(session, bridge_root=tmp_path, limit=20)
        session.expire_all()
        refreshed = session.query(TradeOrder).filter_by(id=result.order.id).one()

        assert summary["orders_scanned"] == 1
        assert summary["leader_paths_ingested"] == 1
        assert summary["paths_ingested"] == 1
        assert refreshed.status == "FILLED"
        assert refreshed.filled_quantity == 1
        assert refreshed.avg_fill_price == 433.11
    finally:
        session.close()


def test_ingest_active_trade_order_events_recovers_low_conf_missing_order(tmp_path):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        result = create_trade_order(
            session,
            {
                "client_order_id": "direct-watchdog-recover-1",
                "symbol": "MYRG",
                "side": "BUY",
                "quantity": 1,
                "order_type": "ADAPTIVE_LMT",
            },
        )
        session.commit()

        update_trade_order_status(session, result.order, {"status": "SUBMITTED"})
        update_trade_order_status(
            session,
            result.order,
            {
                "status": "CANCELED",
                "params": {
                    "event_source": "lean_open_orders",
                    "sync_reason": "missing_from_open_orders",
                },
            },
        )

        (tmp_path / "execution_events.jsonl").write_text(
            (
                '{"order_id":11,"symbol":"MYRG","status":"Filled","filled":1.0,'
                '"fill_price":275.12,"direction":"Buy","time":"2026-02-12T16:37:58Z",'
                f'"tag":"direct:{result.order.id}","exec_id":"ib-fill-recover-1"'
                '}\n'
            ),
            encoding="utf-8",
        )

        summary = ingest_active_trade_order_events(session, bridge_root=tmp_path, limit=20)
        session.expire_all()
        refreshed = session.query(TradeOrder).filter_by(id=result.order.id).one()

        assert summary["orders_scanned"] == 1
        assert summary["leader_paths_ingested"] == 1
        assert summary["paths_ingested"] == 1
        assert refreshed.status == "FILLED"
        assert refreshed.filled_quantity == 1
        assert refreshed.avg_fill_price == 275.12
    finally:
        session.close()


def test_reconcile_low_confidence_terminal_runs_recovers_ended_run(tmp_path):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        run = TradeRun(
            project_id=1,
            status="partial",
            mode="paper",
            params={
                "positions_baseline": {
                    "refreshed_at": "2026-02-12T16:29:52Z",
                    "items": [{"symbol": "SEDG", "quantity": 0.0}],
                }
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        order = create_trade_order(
            session,
            {
                "client_order_id": "oi_999_29",
                "symbol": "SEDG",
                "side": "BUY",
                "quantity": 8,
                "order_type": "ADAPTIVE_LMT",
            },
            run_id=run.id,
        ).order
        session.commit()

        update_trade_order_status(session, order, {"status": "SUBMITTED"})
        update_trade_order_status(
            session,
            order,
            {
                "status": "CANCELED",
                "params": {
                    "event_source": "lean_open_orders",
                    "sync_reason": "missing_from_open_orders",
                },
            },
        )

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        (tmp_path / "positions.json").write_text(
            json.dumps(
                {
                    "items": [{"symbol": "SEDG", "quantity": 8.0, "avg_cost": 34.14}],
                    "refreshed_at": now_iso,
                    "source": "lean_bridge",
                    "stale": False,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "open_orders.json").write_text(
            json.dumps(
                {
                    "items": [],
                    "refreshed_at": now_iso,
                    "source": "lean_bridge",
                    "source_detail": "ib_open_orders_empty",
                    "stale": False,
                }
            ),
            encoding="utf-8",
        )

        summary = reconcile_low_confidence_terminal_runs(
            session,
            bridge_root=tmp_path,
            limit_runs=10,
            order_scan_limit=100,
        )
        session.expire_all()
        refreshed_order = session.query(TradeOrder).filter_by(id=order.id).one()
        refreshed_run = session.get(TradeRun, run.id)

        assert summary["positions_stale"] is False
        assert summary["runs_scanned"] == 1
        assert summary["runs_reconciled"] == 1
        assert summary["orders_reconciled"] == 1
        assert refreshed_order.status == "FILLED"
        assert float(refreshed_order.filled_quantity or 0.0) == 8.0
        assert float(refreshed_order.avg_fill_price or 0.0) == 34.14
        assert refreshed_run is not None
        assert refreshed_run.status == "done"
    finally:
        session.close()


def test_reconcile_active_direct_orders_syncs_submitted_manual_orders(tmp_path):
    from app.services.trade_execution_events_watchdog import reconcile_active_direct_orders

    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        result = create_trade_order(
            session,
            {
                "client_order_id": "direct-watchdog-sync-1",
                "symbol": "AAPL",
                "side": "SELL",
                "quantity": 1,
                "order_type": "MKT",
                "params": {
                    "mode": "paper",
                    "source": "manual",
                    "event_tag": "direct:1",
                    "open_orders_seen_once": True,
                },
            },
        )
        session.commit()
        update_trade_order_status(session, result.order, {"status": "SUBMITTED"})

        now = datetime.now(timezone.utc)
        result.order.updated_at = (now.replace(tzinfo=None))
        session.commit()
        # Make it old enough for direct-order fast finalize path.
        result.order.updated_at = (now - timedelta(seconds=120)).replace(tzinfo=None)
        session.commit()

        (tmp_path / "open_orders.json").write_text(
            json.dumps(
                {
                    "items": [],
                    "refreshed_at": now.isoformat().replace("+00:00", "Z"),
                    "source": "lean_bridge",
                    "source_detail": "ib_open_orders_empty",
                    "stale": False,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "bridge_process.json").write_text(
            json.dumps({"client_id": 0}, ensure_ascii=False),
            encoding="utf-8",
        )

        summary = reconcile_active_direct_orders(session, bridge_root=tmp_path, mode="paper")
        session.expire_all()
        refreshed = session.query(TradeOrder).filter_by(id=result.order.id).one()

        assert summary["sync"]["updated"] == 1
        assert refreshed.status == "CANCELED"
    finally:
        session.close()
