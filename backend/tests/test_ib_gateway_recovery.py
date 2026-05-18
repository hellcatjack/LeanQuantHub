from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import sys
import time

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ib_gateway_runtime import write_gateway_runtime_health

SCRIPT_PATH = REPO_ROOT / "scripts" / "ib_gateway_watchdog.py"
SPEC = importlib.util.spec_from_file_location("ib_gateway_watchdog_script", SCRIPT_PATH)
ib_gateway_watchdog = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(ib_gateway_watchdog)


def _runtime_health(state: str, *, failure_count: int = 0) -> dict[str, object]:
    return {
        "state": state,
        "failure_count": failure_count,
        "pending_command_count": 1,
        "oldest_pending_command_age_seconds": 240,
        "last_positions_at": "2026-03-10T14:00:00Z",
        "last_open_orders_at": "2026-03-10T14:00:00Z",
        "last_account_summary_at": "2026-03-10T14:00:00Z",
        "last_command_result_at": "2026-03-10T14:01:00Z",
        "last_probe_result": "failure",
        "last_probe_latency_ms": 1200,
        "last_recovery_action": None,
        "last_recovery_at": None,
        "next_allowed_action_at": None,
    }


def test_recovery_first_failure_triggers_bridge_refresh(monkeypatch, tmp_path):
    now = datetime(2026, 3, 10, 14, 5, 0, tzinfo=timezone.utc)
    refresh_calls: list[tuple[str, str, bool]] = []

    monkeypatch.setattr(
        ib_gateway_watchdog,
        "build_gateway_runtime_health",
        lambda **_kwargs: _runtime_health("snapshot_stale"),
    )
    monkeypatch.setattr(
        ib_gateway_watchdog,
        "refresh_bridge",
        lambda _session, *, mode, reason, force: refresh_calls.append((mode, reason, force)) or {"status": "ok"},
    )
    monkeypatch.setattr(
        ib_gateway_watchdog,
        "ensure_lean_bridge_leader",
        lambda *_args, **_kwargs: {"status": "ok"},
    )

    result = ib_gateway_watchdog.run_gateway_watchdog_once(
        bridge_root=tmp_path,
        session=None,
        mode="paper",
        now=now,
        direct_probe={"ok": True, "latency_ms": 90},
    )

    assert result["action"] == "bridge_refresh"
    assert refresh_calls == [("paper", "gateway_watchdog", True)]
    assert result["recovery_failure_count"] == 1
    assert result["last_recovery_action"] == "bridge_refresh"


def test_recovery_second_failure_triggers_leader_restart(monkeypatch, tmp_path):
    now = datetime(2026, 3, 10, 14, 6, 0, tzinfo=timezone.utc)
    leader_calls: list[tuple[str, bool]] = []
    write_gateway_runtime_health(
        tmp_path,
        {
            **_runtime_health("snapshot_stale"),
            "recovery_failure_count": 1,
            "last_recovery_action": "bridge_refresh",
            "last_recovery_at": "2026-03-10T14:05:00Z",
        },
    )

    monkeypatch.setattr(
        ib_gateway_watchdog,
        "build_gateway_runtime_health",
        lambda **_kwargs: _runtime_health("snapshot_stale"),
    )
    monkeypatch.setattr(
        ib_gateway_watchdog,
        "refresh_bridge",
        lambda *_args, **_kwargs: {"status": "ok"},
    )
    monkeypatch.setattr(
        ib_gateway_watchdog,
        "ensure_lean_bridge_leader",
        lambda _session, *, mode, force: leader_calls.append((mode, force)) or {"status": "ok"},
    )

    result = ib_gateway_watchdog.run_gateway_watchdog_once(
        bridge_root=tmp_path,
        session=None,
        mode="paper",
        now=now,
        direct_probe={"ok": True, "latency_ms": 90},
    )

    assert result["action"] == "leader_restart"
    assert leader_calls == [("paper", True)]
    assert result["recovery_failure_count"] == 2
    assert result["last_recovery_action"] == "leader_restart"


def test_recovery_escalates_to_systemd_restart_after_threshold(monkeypatch, tmp_path):
    now = datetime(2026, 3, 10, 14, 11, 0, tzinfo=timezone.utc)
    calls: list[list[str]] = []
    write_gateway_runtime_health(
        tmp_path,
        {
            **_runtime_health("bridge_degraded", failure_count=2),
            "recovery_failure_count": 2,
            "last_recovery_action": "leader_restart",
            "last_recovery_at": "2026-03-10T14:06:00Z",
        },
    )

    monkeypatch.setattr(
        ib_gateway_watchdog,
        "build_gateway_runtime_health",
        lambda **_kwargs: _runtime_health("bridge_degraded", failure_count=2),
    )
    monkeypatch.setattr(
        ib_gateway_watchdog,
        "refresh_bridge",
        lambda *_args, **_kwargs: {"status": "ok"},
    )
    monkeypatch.setattr(
        ib_gateway_watchdog,
        "ensure_lean_bridge_leader",
        lambda *_args, **_kwargs: {"status": "ok"},
    )

    result = ib_gateway_watchdog.run_gateway_watchdog_once(
        bridge_root=tmp_path,
        session=None,
        mode="paper",
        now=now,
        direct_probe={"ok": False, "latency_ms": 1500, "error": "timeout"},
        subprocess_run=lambda cmd, **_kwargs: calls.append(cmd) or None,
    )

    assert result["action"] == "gateway_restart"
    assert result["state"] == "gateway_restarting"
    assert calls == [["systemctl", "--user", "restart", "--no-block", "stocklean-ibgateway.service"]]
    assert result["next_allowed_action_at"] is not None


def test_recovery_respects_gateway_restart_cooldown(monkeypatch, tmp_path):
    now = datetime(2026, 3, 10, 14, 12, 0, tzinfo=timezone.utc)
    calls: list[list[str]] = []
    write_gateway_runtime_health(
        tmp_path,
        {
            **_runtime_health("gateway_restarting", failure_count=3),
            "recovery_failure_count": 3,
            "last_recovery_action": "gateway_restart",
            "last_recovery_at": "2026-03-10T14:07:00Z",
            "next_allowed_action_at": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        },
    )

    monkeypatch.setattr(
        ib_gateway_watchdog,
        "build_gateway_runtime_health",
        lambda **_kwargs: _runtime_health("bridge_degraded", failure_count=3),
    )

    result = ib_gateway_watchdog.run_gateway_watchdog_once(
        bridge_root=tmp_path,
        session=None,
        mode="paper",
        now=now,
        direct_probe={"ok": False, "latency_ms": 1500, "error": "timeout"},
        subprocess_run=lambda cmd, **_kwargs: calls.append(cmd) or None,
    )

    assert result["action"] == "gateway_degraded"
    assert result["state"] == "gateway_degraded"
    assert calls == []


def test_recovery_does_not_escalate_during_leader_restart_quiet_period(monkeypatch, tmp_path):
    restart_at = datetime(2026, 3, 10, 14, 6, 0, tzinfo=timezone.utc)
    calls: list[list[str]] = []
    write_gateway_runtime_health(
        tmp_path,
        {
            **_runtime_health("bridge_degraded", failure_count=2),
            "recovery_failure_count": 2,
            "last_recovery_action": "leader_restart",
            "last_recovery_at": restart_at.isoformat().replace("+00:00", "Z"),
        },
    )

    monkeypatch.setattr(
        ib_gateway_watchdog,
        "build_gateway_runtime_health",
        lambda **_kwargs: _runtime_health("bridge_degraded", failure_count=2),
    )
    monkeypatch.setattr(
        ib_gateway_watchdog,
        "ensure_lean_bridge_leader",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("leader restart should not run in quiet period")),
    )
    monkeypatch.setattr(
        ib_gateway_watchdog,
        "refresh_bridge",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("bridge refresh should not run in quiet period")),
    )

    result = ib_gateway_watchdog.run_gateway_watchdog_once(
        bridge_root=tmp_path,
        session=None,
        mode="paper",
        now=restart_at + timedelta(seconds=30),
        direct_probe={"ok": False, "latency_ms": 1500, "error": "timeout"},
        subprocess_run=lambda cmd, **_kwargs: calls.append(cmd) or None,
    )

    assert result["action"] == "none"
    assert result["state"] == "bridge_degraded"
    assert result["recovery_failure_count"] == 2
    assert calls == []


def test_recovery_does_not_repeat_gateway_restart_during_quiet_period(monkeypatch, tmp_path):
    restart_at = datetime(2026, 3, 10, 14, 7, 0, tzinfo=timezone.utc)
    calls: list[list[str]] = []
    write_gateway_runtime_health(
        tmp_path,
        {
            **_runtime_health("gateway_restarting", failure_count=3),
            "recovery_failure_count": 3,
            "last_recovery_action": "gateway_restart",
            "last_recovery_at": restart_at.isoformat().replace("+00:00", "Z"),
            "next_allowed_action_at": (restart_at + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
        },
    )

    monkeypatch.setattr(
        ib_gateway_watchdog,
        "build_gateway_runtime_health",
        lambda **_kwargs: _runtime_health("bridge_degraded", failure_count=3),
    )

    result = ib_gateway_watchdog.run_gateway_watchdog_once(
        bridge_root=tmp_path,
        session=None,
        mode="paper",
        now=restart_at + timedelta(seconds=45),
        direct_probe={"ok": False, "latency_ms": 1500, "error": "timeout"},
        subprocess_run=lambda cmd, **_kwargs: calls.append(cmd) or None,
    )

    assert result["action"] == "none"
    assert result["state"] == "gateway_restarting"
    assert result["recovery_failure_count"] == 3
    assert calls == []


def test_recovery_transitions_from_gateway_restarting_to_recovering_then_healthy(monkeypatch, tmp_path):
    restart_at = datetime(2026, 3, 10, 14, 7, 0, tzinfo=timezone.utc)
    write_gateway_runtime_health(
        tmp_path,
        {
            **_runtime_health("gateway_restarting"),
            "recovery_failure_count": 3,
            "last_recovery_action": "gateway_restart",
            "last_recovery_at": restart_at.isoformat().replace("+00:00", "Z"),
            "next_allowed_action_at": (restart_at + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
        },
    )

    monkeypatch.setattr(
        ib_gateway_watchdog,
        "build_gateway_runtime_health",
        lambda **_kwargs: _runtime_health("healthy", failure_count=0),
    )

    first = ib_gateway_watchdog.run_gateway_watchdog_once(
        bridge_root=tmp_path,
        session=None,
        mode="paper",
        now=restart_at + timedelta(minutes=1),
        direct_probe={"ok": True, "latency_ms": 80},
    )
    second = ib_gateway_watchdog.run_gateway_watchdog_once(
        bridge_root=tmp_path,
        session=None,
        mode="paper",
        now=restart_at + timedelta(minutes=2),
        direct_probe={"ok": True, "latency_ms": 70},
    )

    assert first["action"] == "none"
    assert first["state"] == "recovering"
    assert second["action"] == "none"
    assert second["state"] == "healthy"
    assert second["recovery_failure_count"] == 0


def test_recovery_handles_probe_exception_without_crashing(monkeypatch, tmp_path):
    now = datetime(2026, 3, 10, 14, 9, 0, tzinfo=timezone.utc)
    refresh_calls: list[tuple[str, str, bool]] = []

    monkeypatch.setattr(
        ib_gateway_watchdog,
        "build_gateway_runtime_health",
        lambda **_kwargs: _runtime_health("snapshot_stale"),
    )
    monkeypatch.setattr(
        ib_gateway_watchdog,
        "probe_positions_via_ibapi",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("probe boom")),
    )
    monkeypatch.setattr(
        ib_gateway_watchdog,
        "refresh_bridge",
        lambda _session, *, mode, reason, force: refresh_calls.append((mode, reason, force)) or {"status": "ok"},
    )
    monkeypatch.setattr(
        ib_gateway_watchdog,
        "ensure_lean_bridge_leader",
        lambda *_args, **_kwargs: {"status": "ok"},
    )

    result = ib_gateway_watchdog.run_gateway_watchdog_once(
        bridge_root=tmp_path,
        session=object(),
        mode="paper",
        now=now,
    )

    assert result["action"] == "bridge_refresh"
    assert refresh_calls == [("paper", "gateway_watchdog", True)]


def test_probe_positions_with_hard_timeout_returns_failure_payload(monkeypatch):
    def _slow_probe(_session, *, mode: str, timeout_seconds: float):
        assert mode == "paper"
        assert timeout_seconds == 0.3
        time.sleep(0.2)
        return {"ok": True, "latency_ms": 5, "item_count": 1}

    monkeypatch.setattr(ib_gateway_watchdog, "probe_positions_via_ibapi", _slow_probe)

    payload = ib_gateway_watchdog._probe_positions_with_hard_timeout(
        object(),
        mode="paper",
        timeout_seconds=0.3,
        hard_timeout_seconds=0.05,
        session_factory=lambda: nullcontext(object()),
    )

    assert payload["ok"] is False
    assert payload["error"] == "probe_hard_timeout"
    assert 50 <= payload["latency_ms"] <= 80
    assert payload["item_count"] == 0


def test_collect_gateway_process_probe_calculates_consecutive_hot_cpu(tmp_path):
    now = datetime(2026, 3, 10, 14, 5, 0, tzinfo=timezone.utc)
    previous = {
        "gateway_cpu_sample_at": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "gateway_cpu_usage_nsec": 10_000_000_000,
        "gateway_cpu_hot_count": 1,
    }

    def _fake_run(_cmd, **_kwargs):
        class _Result:
            returncode = 0
            stdout = "\n".join(
                (
                    "MainPID=1234",
                    "CPUUsageNSec=250000000000",
                    "MemoryCurrent=1048576",
                    "TasksCurrent=42",
                )
            )

        return _Result()

    probe = ib_gateway_watchdog._collect_gateway_process_probe(
        service_name="stocklean-ibgateway.service",
        previous_payload=previous,
        now=now,
        subprocess_run=_fake_run,
    )

    assert probe["ok"] is True
    assert probe["main_pid"] == 1234
    assert probe["cpu_usage_nsec"] == 250_000_000_000
    assert probe["cpu_percent"] == 80.0
    assert probe["cpu_hot_count"] == 2
    assert probe["cpu_hot"] is True


def test_run_gateway_watchdog_restarts_gateway_on_hot_gateway_cpu(tmp_path):
    now = datetime(2026, 3, 10, 14, 9, 0, tzinfo=timezone.utc)
    calls: list[list[str]] = []

    result = ib_gateway_watchdog.run_gateway_watchdog_once(
        bridge_root=tmp_path,
        session=None,
        mode="paper",
        now=now,
        direct_probe={"ok": True, "latency_ms": 90, "refreshed_at": now.isoformat().replace("+00:00", "Z")},
        process_probe={
            "ok": True,
            "sampled_at": now.isoformat().replace("+00:00", "Z"),
            "main_pid": 1234,
            "cpu_usage_nsec": 250_000_000_000,
            "cpu_percent": 80.0,
            "cpu_hot": True,
            "cpu_hot_count": 2,
            "cpu_threshold_percent": 75.0,
        },
        subprocess_run=lambda cmd, **_kwargs: calls.append(cmd) or None,
    )

    assert result["action"] == "gateway_restart"
    assert result["state"] == "gateway_restarting"
    assert result["gateway_cpu_hot"] is True
    assert calls == [["systemctl", "--user", "restart", "--no-block", "stocklean-ibgateway.service"]]


def test_run_gateway_watchdog_skips_direct_probe_when_runtime_is_healthy_and_recent(monkeypatch, tmp_path):
    now = datetime(2026, 3, 10, 14, 9, 0, tzinfo=timezone.utc)
    write_gateway_runtime_health(
        tmp_path,
        {
            **_runtime_health("healthy", failure_count=0),
            "pending_command_count": 0,
            "oldest_pending_command_age_seconds": None,
            "last_positions_at": "2026-03-10T14:08:20Z",
            "last_open_orders_at": "2026-03-10T14:08:20Z",
            "last_account_summary_at": "2026-03-10T14:08:20Z",
            "last_probe_result": "success",
            "last_probe_at": "2026-03-10T14:05:30Z",
        },
    )

    monkeypatch.setattr(
        ib_gateway_watchdog,
        "_probe_positions_with_hard_timeout",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("direct probe should be skipped")),
    )
    monkeypatch.setattr(
        ib_gateway_watchdog,
        "build_gateway_runtime_health",
        lambda **_kwargs: {
            **_runtime_health("healthy", failure_count=0),
            "pending_command_count": 0,
            "oldest_pending_command_age_seconds": None,
            "last_positions_at": "2026-03-10T14:08:20Z",
            "last_open_orders_at": "2026-03-10T14:08:20Z",
            "last_account_summary_at": "2026-03-10T14:08:20Z",
            "last_probe_result": "success",
            "last_probe_at": "2026-03-10T14:05:30Z",
        },
    )

    result = ib_gateway_watchdog.run_gateway_watchdog_once(
        bridge_root=tmp_path,
        session=object(),
        mode="paper",
        now=now,
    )

    assert result["action"] == "none"
    assert result["state"] == "healthy"
    assert result["last_probe_result"] == "success"
    assert result["last_probe_at"] == "2026-03-10T14:05:30Z"


def test_watchdog_systemd_unit_template_declares_timeout():
    unit_path = REPO_ROOT / "deploy" / "systemd" / "stocklean-ibgateway-watchdog.service"
    unit_text = unit_path.read_text(encoding="utf-8")

    assert "TimeoutStartSec=30s" in unit_text


def test_watchdog_timer_runs_often_enough_for_cpu_hot_detection():
    timer_path = REPO_ROOT / "deploy" / "systemd" / "stocklean-ibgateway-watchdog.timer"
    timer_text = timer_path.read_text(encoding="utf-8")

    assert "OnUnitActiveSec=5min" in timer_text
