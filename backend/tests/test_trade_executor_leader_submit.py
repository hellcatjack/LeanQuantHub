from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import json
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, TradeOrder, TradeRun, TradeSettings
from app.services import trade_executor
from app.services.lean_bridge_commands import LeanBridgeCommandRef


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


class _DummyLock:
    def __init__(self, *args, **kwargs):
        pass

    def acquire(self):
        return True

    def release(self):
        return None


def test_execute_trade_run_can_submit_via_leader_commands(monkeypatch, tmp_path):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p18", description=""))
        session.commit()

        settings = TradeSettings(risk_defaults={}, execution_data_source="lean", auto_recovery={})
        session.add(settings)
        session.commit()

        intent_path = tmp_path / "intent.json"
        intent_path.write_text(
            json.dumps(
                [
                    {
                        "order_intent_id": "oi_1_1",
                        "symbol": "AAPL",
                        "quantity": 1,
                        "order_type": "ADAPTIVE_LMT",
                    }
                ]
            ),
            encoding="utf-8",
        )
        params_path = tmp_path / "params.json"
        params_path.write_text(
            json.dumps({"min_qty": 1, "lot_size": 1, "unfilled_timeout_seconds": 60}),
            encoding="utf-8",
        )

        run = TradeRun(
            project_id=1,
            decision_snapshot_id=1,
            mode="paper",
            status="queued",
            params={
                "order_intent_path": str(intent_path),
                "execution_params_path": str(params_path),
                "risk_bypass": True,
                "allow_outside_rth": False,
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        order = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="ADAPTIVE_LMT",
            status="NEW",
        )
        session.add(order)
        session.commit()

        bridge_root = tmp_path / "lean_bridge"
        called = {"count": 0}

        def _fake_submit_command(
            commands_dir: Path,
            *,
            symbol: str,
            quantity: float,
            tag: str,
            order_type: str,
            order_id: int | None = None,
            **_kwargs,
        ):
            called["count"] += 1
            assert commands_dir == bridge_root / "commands"
            assert symbol == "AAPL"
            assert float(quantity) == 1.0
            assert tag == "oi_1_1"
            assert order_type == "ADAPTIVE_LMT"
            assert order_id is not None
            command_id = f"submit_order_{order_id}_x"
            return LeanBridgeCommandRef(
                command_id=command_id,
                command_path=str(commands_dir / f"{command_id}.json"),
                requested_at="2026-02-12T00:00:00Z",
                expires_at="2026-02-12T00:02:00Z",
            )

        monkeypatch.setattr(trade_executor, "SessionLocal", Session, raising=False)
        monkeypatch.setattr(trade_executor, "JobLock", _DummyLock, raising=False)
        monkeypatch.setattr(trade_executor, "_resolve_bridge_root", lambda: bridge_root, raising=False)
        monkeypatch.setattr(trade_executor, "_should_use_leader_submit", lambda _p, _o: True, raising=False)
        monkeypatch.setattr(trade_executor, "_is_bridge_ready_for_submit", lambda _r: True, raising=False)
        monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda: True, raising=False)
        monkeypatch.setattr(trade_executor, "write_submit_order_command", _fake_submit_command, raising=False)
        monkeypatch.setattr(
            trade_executor,
            "launch_execution_async",
            lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not launch short-lived executor")),
            raising=False,
        )
        monkeypatch.setattr(trade_executor, "ARTIFACT_ROOT", tmp_path, raising=False)

        result = trade_executor.execute_trade_run(run.id, dry_run=False, force=False)
        assert result.status == "running"
        assert called["count"] == 1

        session.expire_all()
        refreshed_run = session.get(TradeRun, run.id)
        assert refreshed_run is not None
        assert refreshed_run.message == "submitted_leader"
        assert isinstance(refreshed_run.params, dict)
        assert refreshed_run.params["lean_execution"]["source"] == "leader_command"
        refreshed_order = session.get(TradeOrder, order.id)
        assert refreshed_order is not None
        submit_meta = dict((refreshed_order.params or {}).get("submit_command") or {})
        assert submit_meta.get("pending") is True
    finally:
        session.close()


def test_reconcile_submit_command_results_updates_order_status(monkeypatch, tmp_path):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p18", description=""))
        session.commit()
        run = TradeRun(project_id=1, decision_snapshot_id=1, mode="paper", status="running", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        order = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="ADAPTIVE_LMT",
            status="NEW",
            params={"submit_command": {"pending": True, "command_id": "submit_order_1_x"}},
        )
        session.add(order)
        session.commit()

        bridge_root = tmp_path / "lean_bridge"
        result_dir = bridge_root / "command_results"
        result_dir.mkdir(parents=True, exist_ok=True)
        (result_dir / "submit_order_1_x.json").write_text(
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

        updated = trade_executor._reconcile_submit_command_results(session, run, bridge_root=bridge_root)
        assert updated == 1
        session.refresh(order)
        assert order.status == "SUBMITTED"
        submit_meta = dict((order.params or {}).get("submit_command") or {})
        assert submit_meta.get("pending") is False
        assert submit_meta.get("status") == "submitted"
    finally:
        session.close()


def test_execute_trade_run_submits_leader_orders_in_batches(monkeypatch, tmp_path):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p18b", description=""))
        session.commit()

        settings = TradeSettings(risk_defaults={}, execution_data_source="lean", auto_recovery={})
        session.add(settings)
        session.commit()

        items = []
        for idx in range(10):
            items.append(
                {
                    "order_intent_id": f"oi_1_{idx}",
                    "symbol": f"S{idx:02d}",
                    "quantity": 1,
                    "order_type": "ADAPTIVE_LMT",
                }
            )
        intent_path = tmp_path / "intent-batch.json"
        intent_path.write_text(json.dumps(items), encoding="utf-8")
        params_path = tmp_path / "params-batch.json"
        params_path.write_text(
            json.dumps({"min_qty": 1, "lot_size": 1, "unfilled_timeout_seconds": 60}),
            encoding="utf-8",
        )

        run = TradeRun(
            project_id=1,
            decision_snapshot_id=1,
            mode="paper",
            status="queued",
            params={
                "order_intent_path": str(intent_path),
                "execution_params_path": str(params_path),
                "risk_bypass": True,
                "allow_outside_rth": False,
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        for idx in range(10):
            order = TradeOrder(
                run_id=run.id,
                client_order_id=f"oi_1_{idx}",
                symbol=f"S{idx:02d}",
                side="BUY",
                quantity=1,
                order_type="ADAPTIVE_LMT",
                status="NEW",
            )
            session.add(order)
        session.commit()

        bridge_root = tmp_path / "lean_bridge_batch"
        called_symbols: list[str] = []

        def _fake_submit_command(
            commands_dir: Path,
            *,
            symbol: str,
            quantity: float,
            tag: str,
            order_type: str,
            order_id: int | None = None,
            **_kwargs,
        ):
            called_symbols.append(symbol)
            command_id = f"submit_order_{order_id}_batch"
            return LeanBridgeCommandRef(
                command_id=command_id,
                command_path=str(commands_dir / f"{command_id}.json"),
                requested_at="2026-02-12T00:00:00Z",
                expires_at="2026-02-12T00:02:00Z",
            )

        monkeypatch.setattr(trade_executor, "SessionLocal", Session, raising=False)
        monkeypatch.setattr(trade_executor, "JobLock", _DummyLock, raising=False)
        monkeypatch.setattr(trade_executor, "_resolve_bridge_root", lambda: bridge_root, raising=False)
        monkeypatch.setattr(trade_executor, "_should_use_leader_submit", lambda _p, _o: True, raising=False)
        monkeypatch.setattr(trade_executor, "_is_bridge_ready_for_submit", lambda _r: True, raising=False)
        monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda: True, raising=False)
        monkeypatch.setattr(trade_executor, "write_submit_order_command", _fake_submit_command, raising=False)
        monkeypatch.setattr(
            trade_executor,
            "launch_execution_async",
            lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not launch short-lived executor")),
            raising=False,
        )
        monkeypatch.setattr(trade_executor, "fetch_account_summary", lambda _session: {}, raising=False)
        monkeypatch.setattr(trade_executor, "ARTIFACT_ROOT", tmp_path, raising=False)

        result = trade_executor.execute_trade_run(run.id, dry_run=False, force=False)
        assert result.status == "running"

        session.expire_all()
        refreshed_run = session.get(TradeRun, run.id)
        assert refreshed_run is not None
        lean_exec = dict((refreshed_run.params or {}).get("lean_execution") or {})
        assert lean_exec.get("source") == "leader_command"
        assert int(lean_exec.get("batch_size") or 0) == 6
        assert int(lean_exec.get("dispatched_orders") or 0) == 6
        assert int(lean_exec.get("dispatched_batches") or 0) == 1
        assert len(called_symbols) == 6
        assert called_symbols == [f"S{idx:02d}" for idx in range(6)]

        submitted_orders = (
            session.query(TradeOrder)
            .filter(TradeOrder.run_id == run.id)
            .order_by(TradeOrder.id.asc())
            .all()
        )
        assert sum(1 for order in submitted_orders if isinstance(order.params, dict) and (order.params.get("submit_command") or {}).get("command_id")) == 6
        assert sum(1 for order in submitted_orders if not isinstance(order.params, dict) or not (order.params.get("submit_command") or {}).get("command_id")) == 4
    finally:
        session.close()


def test_execute_trade_run_falls_back_when_leader_submit_channel_stuck(monkeypatch, tmp_path):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p19", description=""))
        session.commit()

        settings = TradeSettings(risk_defaults={}, execution_data_source="lean", auto_recovery={})
        session.add(settings)
        session.commit()

        intent_path = tmp_path / "intent.json"
        intent_path.write_text(
            json.dumps(
                [
                    {
                        "order_intent_id": "oi_1_1",
                        "symbol": "AAPL",
                        "quantity": 1,
                        "order_type": "ADAPTIVE_LMT",
                    }
                ]
            ),
            encoding="utf-8",
        )
        params_path = tmp_path / "params.json"
        params_path.write_text(
            json.dumps({"min_qty": 1, "lot_size": 1, "unfilled_timeout_seconds": 60}),
            encoding="utf-8",
        )

        run = TradeRun(
            project_id=1,
            decision_snapshot_id=1,
            mode="paper",
            status="queued",
            params={
                "order_intent_path": str(intent_path),
                "execution_params_path": str(params_path),
                "risk_bypass": True,
                "allow_outside_rth": False,
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        order = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="ADAPTIVE_LMT",
            status="NEW",
        )
        session.add(order)
        session.commit()

        bridge_root = tmp_path / "lean_bridge"
        commands_dir = bridge_root / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)
        stale_file = commands_dir / "submit_order_stale.json"
        stale_file.write_text("{}", encoding="utf-8")
        stale_ts = datetime.now().timestamp() - 60
        os.utime(stale_file, (stale_ts, stale_ts))

        captured: dict[str, object] = {}

        def _fake_build_execution_config(**kwargs):
            captured["client_id"] = kwargs.get("client_id")
            return {"lean-bridge-output-dir": kwargs.get("lean_bridge_output_dir")}

        monkeypatch.setattr(trade_executor, "SessionLocal", Session, raising=False)
        monkeypatch.setattr(trade_executor, "JobLock", _DummyLock, raising=False)
        monkeypatch.setattr(trade_executor, "_resolve_bridge_root", lambda: bridge_root, raising=False)
        monkeypatch.setattr(trade_executor, "_should_use_leader_submit", lambda _p, _o: True, raising=False)
        monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda: True, raising=False)
        monkeypatch.setattr(trade_executor, "read_bridge_status", lambda _root: {"status": "ok", "stale": False}, raising=False)
        monkeypatch.setattr(
            trade_executor,
            "write_submit_order_command",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("leader submit should be skipped")),
            raising=False,
        )
        monkeypatch.setattr(trade_executor, "fetch_account_summary", lambda _session: {}, raising=False)
        monkeypatch.setattr(trade_executor, "build_execution_config", _fake_build_execution_config, raising=False)
        monkeypatch.setattr(trade_executor, "launch_execution_async", lambda **_kwargs: 4321, raising=False)
        monkeypatch.setattr(trade_executor, "ARTIFACT_ROOT", tmp_path, raising=False)

        result = trade_executor.execute_trade_run(run.id, dry_run=False, force=False)
        assert result.status == "running"
        assert result.message == "submitted_lean"

        session.expire_all()
        refreshed_run = session.get(TradeRun, run.id)
        assert refreshed_run is not None
        assert refreshed_run.message == "submitted_lean"
        assert isinstance(refreshed_run.params, dict)
        fallback = dict(refreshed_run.params.get("leader_submit_fallback") or {})
        assert fallback.get("reason") == "command_channel_unhealthy"
        refreshed_order = session.get(TradeOrder, order.id)
        assert refreshed_order is not None
        submit_meta = dict((refreshed_order.params or {}).get("submit_command") or {})
        assert submit_meta == {}
    finally:
        session.close()


def test_leader_submit_channel_ignores_historical_stale_commands(tmp_path):
    bridge_root = tmp_path / "lean_bridge"
    commands_dir = bridge_root / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    stale_file = commands_dir / "submit_order_old.json"
    stale_file.write_text("{}", encoding="utf-8")
    stale_ts = datetime.now().timestamp() - 3600
    os.utime(stale_file, (stale_ts, stale_ts))

    assert trade_executor._is_leader_command_channel_healthy(bridge_root) is True


def test_refresh_trade_run_status_auto_fallbacks_from_stuck_leader_submit(monkeypatch, tmp_path):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p20", description=""))
        session.commit()

        intent_path = tmp_path / "intent.json"
        intent_path.write_text(
            json.dumps(
                [
                    {
                        "order_intent_id": "oi_1_1",
                        "symbol": "AAPL",
                        "quantity": 1,
                        "order_type": "ADAPTIVE_LMT",
                    }
                ]
            ),
            encoding="utf-8",
        )
        params_path = tmp_path / "params.json"
        params_path.write_text(
            json.dumps({"min_qty": 1, "lot_size": 1, "unfilled_timeout_seconds": 60}),
            encoding="utf-8",
        )

        submitted_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        run = TradeRun(
            project_id=1,
            decision_snapshot_id=1,
            mode="paper",
            status="running",
            params={
                "order_intent_path": str(intent_path),
                "execution_params_path": str(params_path),
                "lean_execution": {
                    "source": "leader_command",
                    "submitted_at": submitted_at,
                    "output_dir": str(tmp_path / "leader_run"),
                },
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        order = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="ADAPTIVE_LMT",
            status="NEW",
            params={
                "submit_command": {
                    "pending": True,
                    "command_id": "submit_order_1_test",
                    "requested_at": submitted_at,
                }
            },
        )
        session.add(order)
        session.commit()

        bridge_root = tmp_path / "lean_bridge"
        bridge_root.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(trade_executor, "_resolve_bridge_root", lambda: bridge_root, raising=False)
        monkeypatch.setattr(trade_executor, "read_open_orders", lambda *_args, **_kwargs: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "read_positions", lambda *_args, **_kwargs: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "sync_trade_orders_from_open_orders", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(trade_executor, "ingest_execution_events", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(trade_executor, "_reconcile_submit_command_results", lambda *_args, **_kwargs: 0)
        monkeypatch.setattr(trade_executor, "reconcile_run_with_positions", lambda *_args, **_kwargs: {"reconciled": 0})
        monkeypatch.setattr(trade_executor, "_lean_no_orders_submitted", lambda *_args, **_kwargs: False)
        monkeypatch.setattr(
            trade_executor,
            "build_execution_config",
            lambda **kwargs: {"lean-bridge-output-dir": kwargs.get("lean_bridge_output_dir")},
            raising=False,
        )
        monkeypatch.setattr(trade_executor, "launch_execution_async", lambda **_kwargs: 7788, raising=False)
        monkeypatch.setattr(trade_executor, "ARTIFACT_ROOT", tmp_path, raising=False)

        changed = trade_executor.refresh_trade_run_status(session, run)
        assert changed is True

        session.refresh(run)
        assert run.status == "running"
        assert run.message == "submitted_lean_fallback"
        assert isinstance(run.params, dict)
        assert run.params["lean_execution"]["source"] == "short_lived_fallback"
        fallback_cfg = Path(str(run.params["lean_execution"]["config_path"]))
        cfg_payload = json.loads(fallback_cfg.read_text(encoding="utf-8"))
        assert cfg_payload.get("lean-bridge-exit-on-submit") is False
        fallback = dict(run.params["leader_submit_runtime_fallback"])
        assert fallback["triggered"] is True
        assert fallback["cleared_pending_orders"] == 1

        session.refresh(order)
        submit_meta = dict((order.params or {}).get("submit_command") or {})
        assert submit_meta.get("pending") is False
        assert submit_meta.get("status") == "superseded"
        assert submit_meta.get("superseded_by") == "short_lived_fallback"

        changed_again = trade_executor.refresh_trade_run_status(session, run)
        assert changed_again is False
        session.refresh(run)
        assert run.status == "running"
        assert run.stalled_reason is None
    finally:
        session.close()


def test_refresh_trade_run_status_dispatches_next_leader_batch_when_previous_batch_cleared(monkeypatch, tmp_path):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p20c", description=""))
        session.commit()

        run = TradeRun(
            project_id=1,
            decision_snapshot_id=1,
            mode="paper",
            status="running",
            params={
                "lean_execution": {
                    "source": "leader_command",
                    "submitted_at": "2026-02-12T00:00:00Z",
                    "output_dir": str(tmp_path / "leader_batches"),
                    "batch_size": 6,
                    "dispatched_orders": 6,
                    "dispatched_batches": 1,
                    "current_batch_order_ids": [1, 2, 3, 4, 5, 6],
                }
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        for idx in range(10):
            status = "SUBMITTED" if idx < 6 else "NEW"
            params = (
                {
                    "submit_command": {
                        "pending": False,
                        "source": "leader_command",
                        "status": "submitted",
                        "command_id": f"submit_order_{idx}",
                    }
                }
                if idx < 6
                else {}
            )
            session.add(
                TradeOrder(
                    run_id=run.id,
                    client_order_id=f"oi_next_{idx}",
                    symbol=f"N{idx:02d}",
                    side="BUY",
                    quantity=1,
                    order_type="ADAPTIVE_LMT",
                    status=status,
                    params=params,
                )
            )
        session.commit()

        bridge_root = tmp_path / "lean_bridge_next_batch"
        bridge_root.mkdir(parents=True, exist_ok=True)
        dispatched: dict[str, object] = {}

        def _fake_submit_batch(_session, *, run, orders, params, bridge_root):
            dispatched["symbols"] = [order.symbol for order in orders]
            return {
                "source": "leader_command",
                "submitted_at": "2026-02-12T00:01:00Z",
                "output_dir": str(bridge_root),
                "commands": [{"order_id": order.id, "symbol": order.symbol, "command_id": f"cmd_{order.id}"} for order in orders],
            }

        monkeypatch.setattr(trade_executor, "_resolve_bridge_root", lambda: bridge_root, raising=False)
        monkeypatch.setattr(trade_executor, "read_open_orders", lambda *_args, **_kwargs: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "read_positions", lambda *_args, **_kwargs: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "sync_trade_orders_from_open_orders", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(trade_executor, "ingest_execution_events", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(trade_executor, "_reconcile_submit_command_results", lambda *_args, **_kwargs: 0)
        monkeypatch.setattr(trade_executor, "reconcile_run_with_positions", lambda *_args, **_kwargs: {"reconciled": 0})
        monkeypatch.setattr(trade_executor, "_lean_no_orders_submitted", lambda *_args, **_kwargs: False)
        monkeypatch.setattr(trade_executor, "_submit_run_orders_via_leader", _fake_submit_batch, raising=False)

        changed = trade_executor.refresh_trade_run_status(session, run)

        assert changed is True
        assert dispatched.get("symbols") == [f"N{idx:02d}" for idx in range(6, 10)]
        session.refresh(run)
        lean_exec = dict((run.params or {}).get("lean_execution") or {})
        assert int(lean_exec.get("dispatched_orders") or 0) == 10
        assert int(lean_exec.get("dispatched_batches") or 0) == 2
        assert len(lean_exec.get("current_batch_order_ids") or []) == 4
    finally:
        session.close()


def test_refresh_trade_run_status_keeps_large_leader_batch_running_before_scaled_timeout(monkeypatch, tmp_path):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p20b", description=""))
        session.commit()

        intent_items = []
        submitted_at = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat().replace("+00:00", "Z")
        run = TradeRun(
            project_id=1,
            decision_snapshot_id=1,
            mode="paper",
            status="running",
            params={
                "order_intent_path": str(tmp_path / "intent-large.json"),
                "execution_params_path": str(tmp_path / "params-large.json"),
                "lean_execution": {
                    "source": "leader_command",
                    "submitted_at": submitted_at,
                    "output_dir": str(tmp_path / "leader_large"),
                    "commands": [],
                },
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        for index in range(10):
            symbol = f"T{index:02d}"
            client_order_id = f"oi_large_{index}"
            intent_items.append(
                {
                    "order_intent_id": client_order_id,
                    "symbol": symbol,
                    "quantity": 1,
                    "order_type": "ADAPTIVE_LMT",
                }
            )
            order = TradeOrder(
                run_id=run.id,
                client_order_id=client_order_id,
                symbol=symbol,
                side="BUY",
                quantity=1,
                order_type="ADAPTIVE_LMT",
                status="NEW",
                params={
                    "submit_command": {
                        "pending": True,
                        "source": "leader_command",
                        "command_id": f"submit_order_{index}",
                        "requested_at": submitted_at,
                    }
                },
            )
            session.add(order)
            run_params = dict(run.params or {})
            lean_exec = dict(run_params.get("lean_execution") or {})
            commands = list(lean_exec.get("commands") or [])
            commands.append({"order_id": index + 1, "symbol": symbol, "command_id": f"submit_order_{index}"})
            lean_exec["commands"] = commands
            run_params["lean_execution"] = lean_exec
            run.params = run_params
        session.commit()

        intent_path = Path(str((run.params or {}).get("order_intent_path")))
        intent_path.write_text(json.dumps(intent_items), encoding="utf-8")
        params_path = Path(str((run.params or {}).get("execution_params_path")))
        params_path.write_text(
            json.dumps({"min_qty": 1, "lot_size": 1, "unfilled_timeout_seconds": 60}),
            encoding="utf-8",
        )

        bridge_root = tmp_path / "lean_bridge_large"
        bridge_root.mkdir(parents=True, exist_ok=True)

        fallback_called = {"value": False}

        monkeypatch.setattr(trade_executor, "_resolve_bridge_root", lambda: bridge_root, raising=False)
        monkeypatch.setattr(trade_executor, "read_open_orders", lambda *_args, **_kwargs: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "read_positions", lambda *_args, **_kwargs: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "sync_trade_orders_from_open_orders", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(trade_executor, "ingest_execution_events", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(trade_executor, "_reconcile_submit_command_results", lambda *_args, **_kwargs: 0)
        monkeypatch.setattr(trade_executor, "reconcile_run_with_positions", lambda *_args, **_kwargs: {"reconciled": 0})
        monkeypatch.setattr(trade_executor, "_lean_no_orders_submitted", lambda *_args, **_kwargs: False)

        def _unexpected_fallback(*_args, **_kwargs):
            fallback_called["value"] = True
            return True

        monkeypatch.setattr(
            trade_executor,
            "_launch_short_lived_fallback_for_leader_submit",
            _unexpected_fallback,
            raising=False,
        )

        changed = trade_executor.refresh_trade_run_status(session, run)

        assert changed is False
        assert fallback_called["value"] is False
        session.refresh(run)
        assert run.status == "running"
        assert run.message not in {"submitted_lean_fallback", "stalled"}
    finally:
        session.close()


def test_refresh_trade_run_status_can_recover_stalled_leader_submit(monkeypatch, tmp_path):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p21", description=""))
        session.commit()

        intent_path = tmp_path / "intent-stalled.json"
        intent_path.write_text(
            json.dumps(
                [
                    {
                        "order_intent_id": "oi_1_2",
                        "symbol": "MSFT",
                        "quantity": 1,
                        "order_type": "ADAPTIVE_LMT",
                    }
                ]
            ),
            encoding="utf-8",
        )
        params_path = tmp_path / "params-stalled.json"
        params_path.write_text(
            json.dumps({"min_qty": 1, "lot_size": 1, "unfilled_timeout_seconds": 60}),
            encoding="utf-8",
        )

        submitted_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        run = TradeRun(
            project_id=1,
            decision_snapshot_id=1,
            mode="paper",
            status="stalled",
            message="stalled",
            stalled_reason="submit_command_pending_timeout",
            params={
                "order_intent_path": str(intent_path),
                "execution_params_path": str(params_path),
                "lean_execution": {
                    "source": "leader_command",
                    "submitted_at": submitted_at,
                    "output_dir": str(tmp_path / "leader_run_stalled"),
                },
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        order = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1_2",
            symbol="MSFT",
            side="BUY",
            quantity=1,
            order_type="ADAPTIVE_LMT",
            status="NEW",
            params={
                "submit_command": {
                    "pending": True,
                    "command_id": "submit_order_2_test",
                    "requested_at": submitted_at,
                }
            },
        )
        session.add(order)
        session.commit()

        bridge_root = tmp_path / "lean_bridge_stalled"
        bridge_root.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(trade_executor, "_resolve_bridge_root", lambda: bridge_root, raising=False)
        monkeypatch.setattr(trade_executor, "read_open_orders", lambda *_args, **_kwargs: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "read_positions", lambda *_args, **_kwargs: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "sync_trade_orders_from_open_orders", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(trade_executor, "ingest_execution_events", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(trade_executor, "_reconcile_submit_command_results", lambda *_args, **_kwargs: 0)
        monkeypatch.setattr(trade_executor, "reconcile_run_with_positions", lambda *_args, **_kwargs: {"reconciled": 0})
        monkeypatch.setattr(trade_executor, "_lean_no_orders_submitted", lambda *_args, **_kwargs: False)
        monkeypatch.setattr(
            trade_executor,
            "build_execution_config",
            lambda **kwargs: {"lean-bridge-output-dir": kwargs.get("lean_bridge_output_dir")},
            raising=False,
        )
        monkeypatch.setattr(trade_executor, "launch_execution_async", lambda **_kwargs: 8899, raising=False)
        monkeypatch.setattr(trade_executor, "ARTIFACT_ROOT", tmp_path, raising=False)

        changed = trade_executor.refresh_trade_run_status(session, run)
        assert changed is True

        session.refresh(run)
        assert run.status == "running"
        assert run.message == "submitted_lean_fallback"
        assert isinstance(run.params, dict)
        assert run.params["lean_execution"]["source"] == "short_lived_fallback"
        fallback_cfg = Path(str(run.params["lean_execution"]["config_path"]))
        cfg_payload = json.loads(fallback_cfg.read_text(encoding="utf-8"))
        assert cfg_payload.get("lean-bridge-exit-on-submit") is False
        fallback = dict(run.params["leader_submit_runtime_fallback"])
        assert fallback["triggered"] is True
        assert fallback["cleared_pending_orders"] == 1

        session.refresh(order)
        submit_meta = dict((order.params or {}).get("submit_command") or {})
        assert submit_meta.get("pending") is False
        assert submit_meta.get("status") == "superseded"
        assert submit_meta.get("superseded_by") == "short_lived_fallback"
    finally:
        session.close()


def test_refresh_trade_run_status_auto_resumes_stalled_fallback_run(monkeypatch, tmp_path):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p22", description=""))
        session.commit()

        submitted_at = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        run = TradeRun(
            project_id=1,
            decision_snapshot_id=1,
            mode="paper",
            status="stalled",
            message="submitted_lean_fallback",
            stalled_reason="submit_command_pending_timeout",
            params={
                "lean_execution": {
                    "source": "short_lived_fallback",
                    "submitted_at": submitted_at,
                    "output_dir": str(tmp_path / "fallback_run"),
                },
                "leader_submit_runtime_fallback": {
                    "triggered": True,
                    "triggered_at": submitted_at,
                    "reason": "leader_submit_pending_timeout",
                },
                "submit_command_pending_timeout": {
                    "threshold_seconds": 12,
                    "timed_out": 1,
                },
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        order = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1_3",
            symbol="NVDA",
            side="BUY",
            quantity=1,
            order_type="ADAPTIVE_LMT",
            status="NEW",
            params={
                "submit_command": {
                    "pending": True,
                    "source": "leader_command",
                    "command_id": "submit_order_3_test",
                    "requested_at": submitted_at,
                }
            },
        )
        session.add(order)
        session.commit()

        bridge_root = tmp_path / "lean_bridge_resume"
        bridge_root.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(trade_executor, "_resolve_bridge_root", lambda: bridge_root, raising=False)
        monkeypatch.setattr(trade_executor, "read_open_orders", lambda *_args, **_kwargs: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "read_positions", lambda *_args, **_kwargs: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "sync_trade_orders_from_open_orders", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(trade_executor, "ingest_execution_events", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(trade_executor, "_reconcile_submit_command_results", lambda *_args, **_kwargs: 0)
        monkeypatch.setattr(trade_executor, "reconcile_run_with_positions", lambda *_args, **_kwargs: {"reconciled": 0})
        monkeypatch.setattr(trade_executor, "_lean_no_orders_submitted", lambda *_args, **_kwargs: False)

        changed = trade_executor.refresh_trade_run_status(session, run)
        assert changed is True

        session.refresh(run)
        assert run.status == "running"
        assert run.message == "submitted_lean_fallback"
        assert run.stalled_reason is None
        assert isinstance(run.params, dict)
        assert "submit_command_pending_timeout" not in run.params
        fallback = dict(run.params.get("leader_submit_runtime_fallback") or {})
        assert fallback.get("triggered") is True
        assert fallback.get("auto_resumed_at")
        assert fallback.get("cleared_pending_orders") == 1

        session.refresh(order)
        submit_meta = dict((order.params or {}).get("submit_command") or {})
        assert submit_meta.get("pending") is False
        assert submit_meta.get("status") == "superseded"
        assert submit_meta.get("superseded_by") == "short_lived_fallback"
    finally:
        session.close()


def test_refresh_trade_run_status_ignores_stale_run_open_orders_snapshot(monkeypatch, tmp_path):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p23", description=""))
        session.commit()

        run_root = tmp_path / "run_23"
        run = TradeRun(
            project_id=1,
            decision_snapshot_id=1,
            mode="paper",
            status="running",
            params={
                "lean_execution": {
                    "source": "short_lived_fallback",
                    "submitted_at": "2026-02-12T00:00:00Z",
                    "output_dir": str(run_root),
                }
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        order = TradeOrder(
            run_id=run.id,
            client_order_id="oi_23_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="ADAPTIVE_LMT",
            status="SUBMITTED",
            params={"event_tag": "oi_23_1"},
        )
        session.add(order)
        session.commit()

        bridge_root = tmp_path / "leader_bridge"
        bridge_root.mkdir(parents=True, exist_ok=True)
        stale_run_payload = {
            "items": [{"tag": "oi_23_1", "status": "Submitted"}],
            "refreshed_at": "2026-02-12T00:00:00Z",
            "stale": False,
            "source_detail": "ib_open_orders",
        }
        leader_payload = {
            "items": [],
            "refreshed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "stale": False,
            "source_detail": "ib_open_orders_empty",
        }
        captured = {}

        def _fake_read_open_orders(root):
            if str(root) == str(run_root):
                return stale_run_payload
            return leader_payload

        def _fake_sync(_session, payload, **_kwargs):
            captured["payload"] = payload
            return {}

        monkeypatch.setattr(trade_executor, "_resolve_bridge_root", lambda: bridge_root, raising=False)
        monkeypatch.setattr(trade_executor, "read_open_orders", _fake_read_open_orders, raising=False)
        monkeypatch.setattr(trade_executor, "read_positions", lambda *_args, **_kwargs: {"items": [], "stale": True})
        monkeypatch.setattr(trade_executor, "sync_trade_orders_from_open_orders", _fake_sync, raising=False)
        monkeypatch.setattr(trade_executor, "ingest_execution_events", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(trade_executor, "_reconcile_submit_command_results", lambda *_args, **_kwargs: 0)
        monkeypatch.setattr(trade_executor, "reconcile_run_with_positions", lambda *_args, **_kwargs: {"reconciled": 0})
        monkeypatch.setattr(trade_executor, "_lean_no_orders_submitted", lambda *_args, **_kwargs: False)

        changed = trade_executor.refresh_trade_run_status(session, run)
        assert changed is False
        assert captured.get("payload") == leader_payload
    finally:
        session.close()


def test_refresh_trade_run_status_disables_include_new_while_executor_pid_alive(monkeypatch, tmp_path):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p24", description=""))
        session.commit()

        submitted_at = datetime.now(timezone.utc) - timedelta(seconds=45)
        refreshed_at = datetime.now(timezone.utc)
        run_root = tmp_path / "run_24"
        run = TradeRun(
            project_id=1,
            decision_snapshot_id=1,
            mode="paper",
            status="running",
            params={
                "lean_execution": {
                    "source": "short_lived_fallback",
                    "pid": 424242,
                    "submitted_at": submitted_at.isoformat().replace("+00:00", "Z"),
                    "output_dir": str(run_root),
                }
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        order = TradeOrder(
            run_id=run.id,
            client_order_id="oi_24_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="ADAPTIVE_LMT",
            status="NEW",
            params={"event_tag": "oi_24_1"},
        )
        session.add(order)
        session.commit()

        bridge_root = tmp_path / "leader_bridge_24"
        bridge_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "items": [],
            "refreshed_at": refreshed_at.isoformat().replace("+00:00", "Z"),
            "stale": False,
            "source_detail": "ib_open_orders_empty",
        }
        captured: dict[str, object] = {}

        monkeypatch.setattr(trade_executor, "_resolve_bridge_root", lambda: bridge_root, raising=False)
        monkeypatch.setattr(trade_executor, "_pid_alive", lambda *_args, **_kwargs: True, raising=False)
        monkeypatch.setattr(trade_executor, "read_open_orders", lambda *_args, **_kwargs: payload, raising=False)
        monkeypatch.setattr(trade_executor, "read_positions", lambda *_args, **_kwargs: {"items": [], "stale": True})
        monkeypatch.setattr(
            trade_executor,
            "sync_trade_orders_from_open_orders",
            lambda *_args, **kwargs: captured.update(
                {
                    "include_new": kwargs.get("include_new"),
                    "run_executor_active": kwargs.get("run_executor_active"),
                }
            )
            or {},
            raising=False,
        )
        monkeypatch.setattr(trade_executor, "ingest_execution_events", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(trade_executor, "_reconcile_submit_command_results", lambda *_args, **_kwargs: 0)
        monkeypatch.setattr(trade_executor, "reconcile_run_with_positions", lambda *_args, **_kwargs: {"reconciled": 0})
        monkeypatch.setattr(trade_executor, "_lean_no_orders_submitted", lambda *_args, **_kwargs: False)

        changed = trade_executor.refresh_trade_run_status(session, run)
        assert changed is False
        assert captured.get("include_new") is False
        assert captured.get("run_executor_active") is True
    finally:
        session.close()
