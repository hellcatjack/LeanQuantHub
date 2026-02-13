from pathlib import Path
import sys
import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models import Base
from app.services.lean_bridge_commands import LeanBridgeCommandRef
from app.services import trade_direct_order


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_direct_order_uses_worker_client_id(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))

    captured = {}

    def _fake_build_execution_config(**kwargs):
        captured["client_id"] = kwargs.get("client_id")
        return {"lean-bridge-output-dir": kwargs.get("lean_bridge_output_dir")}

    monkeypatch.setattr(trade_direct_order, "build_execution_config", _fake_build_execution_config)
    monkeypatch.setattr(trade_direct_order, "launch_execution_async", lambda *_args, **_kwargs: 4321)
    monkeypatch.setattr(trade_direct_order, "lease_client_id", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("lease_client_id should not be called")))
    monkeypatch.setattr(trade_direct_order, "_select_worker", lambda *_args, **_kwargs: 2001)

    session = _make_session()
    payload = {
        "project_id": 1,
        "mode": "paper",
        "client_order_id": "manual-1",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "order_type": "MKT",
        "params": {"client_order_id_auto": True},
    }
    result = trade_direct_order.submit_direct_order(session, payload)
    assert result.execution_status == "submitted_lean"
    assert captured["client_id"] == 2001


def test_direct_order_prefers_leader_submit_for_adaptive_lmt(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))

    bridge_root = tmp_path / "data" / "lean_bridge"
    commands_dir = bridge_root / "commands"
    captured = {}

    def _fake_write_submit_order_command(
        target_dir: Path,
        *,
        symbol: str,
        quantity: float,
        tag: str,
        order_type: str,
        order_id: int | None = None,
        **_kwargs,
    ):
        captured["dir"] = target_dir
        captured["symbol"] = symbol
        captured["quantity"] = quantity
        captured["tag"] = tag
        captured["order_type"] = order_type
        command_id = f"submit_order_{int(order_id or 0)}_x"
        return LeanBridgeCommandRef(
            command_id=command_id,
            command_path=str(target_dir / f"{command_id}.json"),
            requested_at="2026-02-12T00:00:00Z",
            expires_at="2026-02-12T00:02:00Z",
        )

    monkeypatch.setattr(trade_direct_order, "resolve_bridge_root", lambda: bridge_root, raising=False)
    monkeypatch.setattr(trade_direct_order, "read_bridge_status", lambda _root: {"status": "ok", "stale": False}, raising=False)
    monkeypatch.setattr(trade_direct_order, "write_submit_order_command", _fake_write_submit_order_command, raising=False)
    monkeypatch.setattr(
        trade_direct_order,
        "launch_execution_async",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("short-lived executor should not launch")),
    )
    monkeypatch.setattr(trade_direct_order, "refresh_bridge", lambda *_args, **_kwargs: {"last_refresh_result": "success"})

    session = _make_session()
    payload = {
        "project_id": 1,
        "mode": "paper",
        "client_order_id": "leader-adaptive-1",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 2,
        "order_type": "ADAPTIVE_LMT",
        "params": {"client_order_id_auto": True},
    }
    result = trade_direct_order.submit_direct_order(session, payload)
    assert result.execution_status == "submitted_leader"
    assert captured["dir"] == commands_dir
    assert captured["symbol"] == "AAPL"
    assert float(captured["quantity"]) == 2.0
    assert captured["order_type"] == "ADAPTIVE_LMT"

    order = session.query(trade_direct_order.TradeOrder).first()
    assert order is not None
    submit_meta = dict((order.params or {}).get("submit_command") or {})
    assert submit_meta.get("pending") is True
    assert submit_meta.get("source") == "leader_command"


def test_direct_order_prefers_leader_submit_for_lmt(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))

    bridge_root = tmp_path / "data" / "lean_bridge"
    commands_dir = bridge_root / "commands"
    captured = {}

    def _fake_write_submit_order_command(
        target_dir: Path,
        *,
        symbol: str,
        quantity: float,
        tag: str,
        order_type: str,
        order_id: int | None = None,
        **kwargs,
    ):
        captured["dir"] = target_dir
        captured["symbol"] = symbol
        captured["quantity"] = quantity
        captured["tag"] = tag
        captured["order_type"] = order_type
        captured["limit_price"] = kwargs.get("limit_price")
        command_id = f"submit_order_{int(order_id or 0)}_x"
        return LeanBridgeCommandRef(
            command_id=command_id,
            command_path=str(target_dir / f"{command_id}.json"),
            requested_at="2026-02-12T00:00:00Z",
            expires_at="2026-02-12T00:02:00Z",
        )

    monkeypatch.setattr(trade_direct_order, "resolve_bridge_root", lambda: bridge_root, raising=False)
    monkeypatch.setattr(trade_direct_order, "read_bridge_status", lambda _root: {"status": "ok", "stale": False}, raising=False)
    monkeypatch.setattr(trade_direct_order, "write_submit_order_command", _fake_write_submit_order_command, raising=False)
    monkeypatch.setattr(
        trade_direct_order,
        "launch_execution_async",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("short-lived executor should not launch")),
    )
    monkeypatch.setattr(trade_direct_order, "refresh_bridge", lambda *_args, **_kwargs: {"last_refresh_result": "success"})

    session = _make_session()
    payload = {
        "project_id": 1,
        "mode": "paper",
        "client_order_id": "leader-lmt-1",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 2,
        "order_type": "LMT",
        "limit_price": 188.12,
        "params": {"client_order_id_auto": True},
    }
    result = trade_direct_order.submit_direct_order(session, payload)
    assert result.execution_status == "submitted_leader"
    assert captured["dir"] == commands_dir
    assert captured["symbol"] == "AAPL"
    assert float(captured["quantity"]) == 2.0
    assert captured["order_type"] == "LMT"
    assert float(captured["limit_price"]) == 188.12

    order = session.query(trade_direct_order.TradeOrder).first()
    assert order is not None
    submit_meta = dict((order.params or {}).get("submit_command") or {})
    assert submit_meta.get("pending") is True
    assert submit_meta.get("source") == "leader_command"
    assert (order.params or {}).get("event_tag") == "leader-lmt-1"
    assert (order.params or {}).get("broker_order_tag") == "leader-lmt-1"


def test_direct_order_falls_back_when_leader_submit_channel_stuck(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))

    bridge_root = tmp_path / "data" / "lean_bridge"
    commands_dir = bridge_root / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    stale_file = commands_dir / "submit_order_stale.json"
    stale_file.write_text("{}", encoding="utf-8")
    stale_ts = datetime.now().timestamp() - 60
    os.utime(stale_file, (stale_ts, stale_ts))

    captured = {}

    def _fake_build_execution_config(**kwargs):
        captured["client_id"] = kwargs.get("client_id")
        return {"lean-bridge-output-dir": kwargs.get("lean_bridge_output_dir")}

    monkeypatch.setattr(trade_direct_order, "resolve_bridge_root", lambda: bridge_root, raising=False)
    monkeypatch.setattr(trade_direct_order, "read_bridge_status", lambda _root: {"status": "ok", "stale": False}, raising=False)
    monkeypatch.setattr(
        trade_direct_order,
        "write_submit_order_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("leader submit should be skipped")),
        raising=False,
    )
    monkeypatch.setattr(trade_direct_order, "build_execution_config", _fake_build_execution_config)
    monkeypatch.setattr(trade_direct_order, "launch_execution_async", lambda *_args, **_kwargs: 4321)
    monkeypatch.setattr(trade_direct_order, "_select_worker", lambda *_args, **_kwargs: 2001)

    session = _make_session()
    payload = {
        "project_id": 1,
        "mode": "paper",
        "client_order_id": "fallback-adaptive-1",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "order_type": "ADAPTIVE_LMT",
        "params": {"client_order_id_auto": True},
    }
    result = trade_direct_order.submit_direct_order(session, payload)
    assert result.execution_status == "submitted_lean"
    assert captured["client_id"] == 2001


def test_direct_order_leader_channel_ignores_historical_stale_commands(tmp_path):
    bridge_root = tmp_path / "lean_bridge"
    commands_dir = bridge_root / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    stale_file = commands_dir / "submit_order_old.json"
    stale_file.write_text("{}", encoding="utf-8")
    stale_ts = datetime.now().timestamp() - 3600
    os.utime(stale_file, (stale_ts, stale_ts))

    assert trade_direct_order._is_leader_command_channel_healthy(bridge_root) is True


def test_direct_order_adaptive_lmt_drops_limit_price(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))
    monkeypatch.setattr(trade_direct_order, "launch_execution_async", lambda *_args, **_kwargs: 4321)
    monkeypatch.setattr(trade_direct_order, "_select_worker", lambda *_args, **_kwargs: 2001)
    monkeypatch.setattr(
        trade_direct_order,
        "_resolve_limit_price_from_bridge",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("adaptive should not request bridge limit price")),
    )

    session = _make_session()
    payload = {
        "project_id": 1,
        "mode": "paper",
        "client_order_id": "adaptive-1",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "order_type": "ADAPTIVE_LMT",
        "limit_price": 188.88,
        "params": {"client_order_id_auto": True, "submit_via_leader": False},
    }
    result = trade_direct_order.submit_direct_order(session, payload)
    assert result.execution_status == "submitted_lean"

    order = session.query(trade_direct_order.TradeOrder).first()
    assert order is not None
    assert order.order_type == "ADAPTIVE_LMT"
    assert order.limit_price is None


def test_direct_order_intent_includes_prime_price(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))
    monkeypatch.setattr(trade_direct_order, "launch_execution_async", lambda *_args, **_kwargs: 4321)
    monkeypatch.setattr(trade_direct_order, "_select_worker", lambda *_args, **_kwargs: 2001)
    monkeypatch.setattr(trade_direct_order, "resolve_price_seed", lambda *_args, **_kwargs: 188.75, raising=False)

    session = _make_session()
    payload = {
        "project_id": 1,
        "mode": "paper",
        "client_order_id": "prime-1",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "order_type": "ADAPTIVE_LMT",
        "params": {"client_order_id_auto": True, "submit_via_leader": False},
    }
    result = trade_direct_order.submit_direct_order(session, payload)
    assert result.execution_status == "submitted_lean"

    order = session.query(trade_direct_order.TradeOrder).first()
    assert order is not None
    intent_path = Path(settings.artifact_root) / "order_intents" / f"order_intent_direct_{order.id}.json"
    payload_items = json.loads(intent_path.read_text(encoding="utf-8"))
    assert payload_items[0]["prime_price"] == 188.75


def _create_retry_pending_order(session, monkeypatch):
    monkeypatch.setattr(trade_direct_order, "refresh_bridge", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(trade_direct_order, "build_execution_config", lambda **kwargs: {"client_id": kwargs.get("client_id")})
    monkeypatch.setattr(trade_direct_order, "launch_execution_async", lambda *_args, **_kwargs: 4321)
    monkeypatch.setattr(trade_direct_order, "_select_worker", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        trade_direct_order,
        "lease_client_id",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(trade_direct_order.ClientIdPoolExhausted("client_id_busy")),
    )
    payload = {
        "project_id": 1,
        "mode": "paper",
        "client_order_id": "retry-pending",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "order_type": "MKT",
        "params": {"client_order_id_auto": True},
    }
    result = trade_direct_order.submit_direct_order(session, payload)
    assert result.execution_status == "retry_pending"
    order = session.query(trade_direct_order.TradeOrder).one()
    return order


def test_retry_pending_direct_orders_retries_due_order(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))

    session = _make_session()
    order = _create_retry_pending_order(session, monkeypatch)
    params = dict(order.params or {})
    meta = dict(params.get("direct_retry") or {})
    due_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    meta["next_retry_at"] = due_at.isoformat().replace("+00:00", "Z")
    params["direct_retry"] = meta
    order.params = params
    session.commit()

    monkeypatch.setattr(trade_direct_order, "_select_worker", lambda *_args, **_kwargs: 2001)

    summary = trade_direct_order.retry_pending_direct_orders(
        session,
        mode="paper",
        now=due_at + timedelta(seconds=1),
    )
    assert summary["scanned"] == 1
    assert summary["retried"] == 1
    assert summary["submitted"] == 1
    session.refresh(order)
    refreshed_meta = dict((order.params or {}).get("direct_retry") or {})
    assert refreshed_meta.get("pending") is False
    assert refreshed_meta.get("last_reason") == "submitted"


def test_retry_pending_direct_orders_skips_not_due(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))

    session = _make_session()
    order = _create_retry_pending_order(session, monkeypatch)
    params = dict(order.params or {})
    meta = dict(params.get("direct_retry") or {})
    due_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    meta["next_retry_at"] = due_at.isoformat().replace("+00:00", "Z")
    params["direct_retry"] = meta
    order.params = params
    session.commit()

    monkeypatch.setattr(trade_direct_order, "_select_worker", lambda *_args, **_kwargs: 2001)

    summary = trade_direct_order.retry_pending_direct_orders(
        session,
        mode="paper",
        now=datetime.now(timezone.utc),
    )
    assert summary["scanned"] == 1
    assert summary["retried"] == 0
    assert summary["skipped_not_due"] == 1
    session.refresh(order)
    refreshed_meta = dict((order.params or {}).get("direct_retry") or {})
    assert refreshed_meta.get("pending") is True


def test_retry_direct_order_force_short_lived_supersedes_submit_command(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))

    session = _make_session()
    order_payload = {
        "client_order_id": "direct-force-fallback-1",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "order_type": "ADAPTIVE_LMT",
        "params": {
            "mode": "paper",
            "project_id": 1,
            "submit_command": {
                "pending": True,
                "source": "leader_command",
                "command_id": "submit_order_force_1",
                "requested_at": "2026-02-12T00:00:00Z",
            },
        },
    }
    result = trade_direct_order.create_trade_order(session, order_payload)
    session.commit()
    session.refresh(result.order)
    order = result.order

    monkeypatch.setattr(
        trade_direct_order,
        "_launch_direct_execution",
        lambda *_args, **_kwargs: trade_direct_order.TradeDirectOrderOut(
            order_id=order.id,
            status="NEW",
            execution_status="submitted_lean",
            intent_path="intent",
            config_path="config",
        ),
    )

    out = trade_direct_order.retry_direct_order(
        session,
        order_id=order.id,
        reason="leader_submit_pending_timeout",
        force=False,
        force_short_lived=True,
    )
    assert out.execution_status == "submitted_lean"
    session.refresh(order)
    submit_meta = dict((order.params or {}).get("submit_command") or {})
    assert submit_meta.get("pending") is False
    assert submit_meta.get("status") == "superseded"
    assert submit_meta.get("superseded_by") == "short_lived_fallback"
    assert submit_meta.get("reason") == "leader_submit_pending_timeout"


def test_retry_pending_direct_orders_retries_timed_out_leader_submit(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))

    session = _make_session()
    order_payload = {
        "client_order_id": "direct-timeout-1",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "order_type": "ADAPTIVE_LMT",
        "params": {
            "mode": "paper",
            "project_id": 1,
            "direct_retry": {
                "pending": False,
                "count": 1,
                "next_retry_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            },
            "submit_command": {
                "pending": True,
                "source": "leader_command",
                "command_id": "submit_order_timeout_1",
                "requested_at": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
            },
        },
    }
    result = trade_direct_order.create_trade_order(session, order_payload)
    session.commit()
    session.refresh(result.order)
    order = result.order

    captured: dict[str, object] = {}

    def _fake_retry_direct_order(
        _session,
        *,
        order_id: int,
        reason: str | None = None,
        force: bool = False,
        force_short_lived: bool = False,
    ):
        captured["order_id"] = order_id
        captured["reason"] = reason
        captured["force"] = force
        captured["force_short_lived"] = force_short_lived
        return trade_direct_order.TradeDirectOrderOut(
            order_id=order_id,
            status="NEW",
            execution_status="submitted_lean",
            intent_path="intent",
            config_path="config",
        )

    monkeypatch.setattr(trade_direct_order, "retry_direct_order", _fake_retry_direct_order)

    summary = trade_direct_order.retry_pending_direct_orders(
        session,
        mode="paper",
        now=datetime.now(timezone.utc),
    )
    assert summary["scanned_leader_pending"] == 1
    assert summary["retried"] == 1
    assert summary["submitted"] == 1
    assert summary["leader_timeout_retried"] == 1
    assert captured["order_id"] == order.id
    assert captured["reason"] == "leader_submit_pending_timeout"
    assert captured["force_short_lived"] is True


def test_reconcile_direct_submit_command_results_updates_submitted(tmp_path):
    session = _make_session()
    order_payload = {
        "client_order_id": "direct-submit-1",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "order_type": "ADAPTIVE_LMT",
        "params": {
            "event_tag": "direct:1",
            "submit_command": {"pending": True, "command_id": "submit_order_1_x"},
        },
    }
    result = trade_direct_order.create_trade_order(session, order_payload)
    session.commit()
    session.refresh(result.order)
    order = result.order

    bridge_root = tmp_path / "lean_bridge"
    results_dir = bridge_root / "command_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "submit_order_1_x.json").write_text(
        json.dumps(
            {
                "command_id": "submit_order_1_x",
                "type": "submit_order",
                "status": "submitted",
                "processed_at": "2026-02-12T00:00:05Z",
            }
        ),
        encoding="utf-8",
    )

    summary = trade_direct_order.reconcile_direct_submit_command_results(session, bridge_root=bridge_root)
    assert summary["submitted"] == 1
    session.refresh(order)
    assert order.status == "SUBMITTED"
    submit_meta = dict((order.params or {}).get("submit_command") or {})
    assert submit_meta.get("pending") is False
    assert submit_meta.get("status") == "submitted"


def test_reconcile_direct_submit_command_results_updates_rejected(tmp_path):
    session = _make_session()
    order_payload = {
        "client_order_id": "direct-submit-2",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "order_type": "ADAPTIVE_LMT",
        "params": {
            "event_tag": "direct:2",
            "submit_command": {"pending": True, "command_id": "submit_order_2_x"},
        },
    }
    result = trade_direct_order.create_trade_order(session, order_payload)
    session.commit()
    session.refresh(result.order)
    order = result.order

    bridge_root = tmp_path / "lean_bridge"
    results_dir = bridge_root / "command_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "submit_order_2_x.json").write_text(
        json.dumps(
            {
                "command_id": "submit_order_2_x",
                "type": "submit_order",
                "status": "place_failed",
                "error": "ib_not_connected",
            }
        ),
        encoding="utf-8",
    )

    summary = trade_direct_order.reconcile_direct_submit_command_results(session, bridge_root=bridge_root)
    assert summary["rejected"] == 1
    session.refresh(order)
    assert order.status == "REJECTED"
    assert order.rejected_reason == "ib_not_connected"
