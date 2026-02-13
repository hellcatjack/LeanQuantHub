from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models import AuditLog, Base, TradeOrder


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_request_cancel_trade_order_enqueues_command_and_sets_status(tmp_path, monkeypatch):
    from app.services.trade_cancel import request_cancel_trade_order

    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    bridge_root = tmp_path / "lean_bridge"
    bridge_root.mkdir(parents=True, exist_ok=True)

    session = _make_session()
    try:
        order = TradeOrder(
            run_id=None,
            client_order_id="manual-abc",
            symbol="AAPL",
            side="BUY",
            quantity=1.0,
            order_type="LMT",
            limit_price=100.0,
            status="NEW",
            params={"mode": "paper"},
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        updated = request_cancel_trade_order(session, order=order, actor="user")
        assert updated.status == "CANCEL_REQUESTED"
        assert isinstance(updated.params, dict)
        assert updated.params.get("user_cancel_requested") is True
        assert "user_cancel" in updated.params
        user_cancel = updated.params["user_cancel"]
        assert isinstance(user_cancel, dict)
        assert user_cancel.get("tag") == "manual-abc"

        commands_dir = bridge_root / f"direct_{order.id}" / "commands"
        assert commands_dir.exists()
        files = sorted(commands_dir.glob("cancel_order_*.json"))
        assert files, "expected a cancel command to be written"

        audit = session.query(AuditLog).filter(AuditLog.resource_id == order.id).all()
        assert any(row.action == "trade_order.cancel_requested" for row in audit)
    finally:
        session.close()


def test_request_cancel_trade_order_for_run_uses_run_output_dir(tmp_path, monkeypatch):
    from app.services.trade_cancel import request_cancel_trade_order

    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    bridge_root = tmp_path / "lean_bridge"
    bridge_root.mkdir(parents=True, exist_ok=True)

    session = _make_session()
    try:
        run_output_dir = tmp_path / "lean_bridge_runs" / "run_42"
        run_output_dir.mkdir(parents=True, exist_ok=True)

        from app.models import TradeRun

        trade_run = TradeRun(
            project_id=1,
            mode="paper",
            status="running",
            params={"lean_execution": {"output_dir": str(run_output_dir)}},
        )
        session.add(trade_run)
        session.commit()
        session.refresh(trade_run)

        order = TradeOrder(
            run_id=trade_run.id,
            client_order_id="oi_abc",
            symbol="AAPL",
            side="BUY",
            quantity=1.0,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={"mode": "paper", "event_tag": "oi_abc"},
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        updated = request_cancel_trade_order(session, order=order, actor="user")
        assert updated.status == "CANCEL_REQUESTED"
        assert isinstance(updated.params, dict)
        user_cancel = updated.params.get("user_cancel") or {}
        assert user_cancel.get("tag") == "oi_abc"

        commands_dir = run_output_dir / "commands"
        assert commands_dir.exists()
        files = sorted(commands_dir.glob("cancel_order_*.json"))
        assert files, "expected a cancel command to be written under run output dir"
    finally:
        session.close()


def test_request_cancel_trade_order_prefers_broker_order_tag(tmp_path, monkeypatch):
    from app.services.trade_cancel import request_cancel_trade_order

    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    bridge_root = tmp_path / "lean_bridge"
    bridge_root.mkdir(parents=True, exist_ok=True)

    session = _make_session()
    try:
        order = TradeOrder(
            run_id=None,
            client_order_id="manual-xyz",
            symbol="AAPL",
            side="BUY",
            quantity=1.0,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={
                "mode": "paper",
                "event_tag": "direct:9999",
                "broker_order_tag": "manual-xyz",
            },
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        updated = request_cancel_trade_order(session, order=order, actor="user")
        user_cancel = dict((updated.params or {}).get("user_cancel") or {})
        assert user_cancel.get("tag") == "manual-xyz"
    finally:
        session.close()


def test_request_cancel_trade_order_leader_submit_uses_bridge_root_commands(tmp_path, monkeypatch):
    from app.services.trade_cancel import request_cancel_trade_order

    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    bridge_root = tmp_path / "lean_bridge"
    bridge_root.mkdir(parents=True, exist_ok=True)

    session = _make_session()
    try:
        order = TradeOrder(
            run_id=None,
            client_order_id="manual-leader-1",
            symbol="AAPL",
            side="SELL",
            quantity=1.0,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={
                "mode": "paper",
                "event_source": "lean_command",
                "sync_reason": "submit_command_submitted",
                "submit_command": {
                    "source": "leader_command",
                    "command_path": str(bridge_root / "commands" / "submit_order_1_1.json"),
                },
            },
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        updated = request_cancel_trade_order(session, order=order, actor="user")
        assert updated.status == "CANCEL_REQUESTED"

        user_cancel = dict((updated.params or {}).get("user_cancel") or {})
        assert user_cancel.get("output_dir") == str(bridge_root)
        command_path = Path(str(user_cancel.get("command_path") or ""))
        assert command_path.parent == bridge_root / "commands"

        files = sorted((bridge_root / "commands").glob("cancel_order_*.json"))
        assert files, "expected a cancel command to be written under bridge root commands"
        assert not (bridge_root / f"direct_{order.id}" / "commands").exists()
    finally:
        session.close()


def test_request_cancel_trade_order_falls_back_to_client_order_id_for_legacy_direct_event_tag(tmp_path, monkeypatch):
    from app.services.trade_cancel import request_cancel_trade_order

    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    bridge_root = tmp_path / "lean_bridge"
    bridge_root.mkdir(parents=True, exist_ok=True)

    session = _make_session()
    try:
        order = TradeOrder(
            run_id=None,
            client_order_id="oi_legacy_1",
            symbol="AAPL",
            side="BUY",
            quantity=1.0,
            order_type="LMT",
            limit_price=100.0,
            status="SUBMITTED",
            params={
                "mode": "paper",
                "event_tag": "direct:5001",
            },
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        updated = request_cancel_trade_order(session, order=order, actor="user")
        user_cancel = dict((updated.params or {}).get("user_cancel") or {})
        assert user_cancel.get("tag") == "oi_legacy_1"
    finally:
        session.close()


def test_reconcile_cancel_requested_orders_marks_terminal_from_command_results(tmp_path):
    from app.services.trade_cancel import reconcile_cancel_requested_orders

    session = _make_session()
    try:
        output_dir = tmp_path / "run_1"
        results_dir = output_dir / "command_results"
        results_dir.mkdir(parents=True, exist_ok=True)

        order = TradeOrder(
            run_id=None,
            client_order_id="oi_1_1",
            symbol="AAPL",
            side="BUY",
            quantity=1.0,
            order_type="LMT",
            limit_price=100.0,
            status="CANCEL_REQUESTED",
            params={
                "user_cancel": {
                    "tag": "oi_1_1",
                    "command_id": "cancel_order_1_123",
                    "output_dir": str(output_dir),
                }
            },
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        (results_dir / "cancel_order_1_123.json").write_text(
            """
            {
              "command_id": "cancel_order_1_123",
              "type": "cancel_order",
              "status": "not_found",
              "processed_at": "2026-02-10T19:01:35Z",
              "order_id": 1,
              "tag": "oi_1_1",
              "found": 0,
              "sent": 0,
              "symbols": [],
              "brokerage_ids": [],
              "source": "lean_bridge"
            }
            """.strip(),
            encoding="utf-8",
        )

        summary = reconcile_cancel_requested_orders(session)
        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "CANCELED"
        assert summary["updated"] == 1
    finally:
        session.close()


def test_reconcile_cancel_requested_orders_falls_back_to_leader_result_root(tmp_path, monkeypatch):
    from app.services.trade_cancel import reconcile_cancel_requested_orders

    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    bridge_root = tmp_path / "lean_bridge"
    (bridge_root / "command_results").mkdir(parents=True, exist_ok=True)

    session = _make_session()
    try:
        stale_output_dir = bridge_root / "direct_1"
        (stale_output_dir / "commands").mkdir(parents=True, exist_ok=True)

        order = TradeOrder(
            run_id=None,
            client_order_id="manual-leader-2",
            symbol="AAPL",
            side="SELL",
            quantity=1.0,
            order_type="LMT",
            limit_price=100.0,
            status="CANCEL_REQUESTED",
            params={
                "event_source": "lean_command",
                "sync_reason": "submit_command_submitted",
                "submit_command": {
                    "source": "leader_command",
                    "command_path": str(bridge_root / "commands" / "submit_order_2_1.json"),
                },
                "user_cancel": {
                    "tag": "manual-leader-2",
                    "command_id": "cancel_order_2_123",
                    "output_dir": str(stale_output_dir),
                },
            },
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        (bridge_root / "command_results" / "cancel_order_2_123.json").write_text(
            """
            {
              "command_id": "cancel_order_2_123",
              "type": "cancel_order",
              "status": "ok",
              "processed_at": "2026-02-13T04:22:00Z",
              "order_id": 2,
              "tag": "manual-leader-2",
              "found": 1,
              "sent": 1,
              "symbols": ["AAPL"],
              "brokerage_ids": ["12345"],
              "source": "lean_bridge"
            }
            """.strip(),
            encoding="utf-8",
        )

        summary = reconcile_cancel_requested_orders(session)
        refreshed = session.get(TradeOrder, order.id)
        assert refreshed.status == "CANCELED"
        assert summary["updated"] == 1
    finally:
        session.close()
