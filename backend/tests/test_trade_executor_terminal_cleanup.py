from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, TradeRun
from app.services import trade_executor


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_cleanup_terminal_run_processes_terminates_short_lived_pid(monkeypatch):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p18", description=""))
        session.commit()

        run = TradeRun(
            project_id=1,
            decision_snapshot_id=1,
            mode="paper",
            status="failed",
            params={
                "lean_execution": {
                    "pid": 43210,
                    "source": "short_lived_fallback",
                    "output_dir": "/tmp/lean_bridge_runs/run_1",
                }
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        pid_alive = {43210: True}
        terminate_calls: list[tuple[int, bool]] = []

        def _fake_pid_alive(pid):
            try:
                return bool(pid_alive.get(int(pid), False))
            except Exception:
                return False

        def _fake_terminate(pid, *, force=False):
            pid_value = int(pid)
            terminate_calls.append((pid_value, bool(force)))
            pid_alive[pid_value] = False
            return True

        monkeypatch.setattr(trade_executor, "_pid_alive", _fake_pid_alive, raising=False)
        monkeypatch.setattr(trade_executor, "_terminate_pid", _fake_terminate, raising=False)
        monkeypatch.setattr(trade_executor, "_resolve_bridge_root", lambda: Path("/tmp/lean_bridge"), raising=False)

        cleaned = trade_executor.cleanup_terminal_run_processes(session, limit=10)
        session.commit()
        session.refresh(run)

        assert cleaned == 1
        assert terminate_calls == [(43210, False)]
        lean_exec = dict((run.params or {}).get("lean_execution") or {})
        cleanup = dict((run.params or {}).get("lean_execution_cleanup") or {})
        assert lean_exec.get("pid") is None
        assert lean_exec.get("terminated_reason") == "run_terminal_status"
        assert cleanup.get("pid") == 43210
        assert cleanup.get("alive_after") is False
    finally:
        session.close()


def test_cleanup_terminal_run_processes_skips_leader_command_pid(monkeypatch):
    Session = _make_session()
    session = Session()
    try:
        session.add(Project(name="p18", description=""))
        session.commit()

        run = TradeRun(
            project_id=1,
            decision_snapshot_id=1,
            mode="paper",
            status="failed",
            params={
                "lean_execution": {
                    "pid": 55667,
                    "source": "leader_command",
                    "output_dir": "/tmp/lean_bridge",
                }
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        terminate_calls: list[tuple[int, bool]] = []

        monkeypatch.setattr(trade_executor, "_pid_alive", lambda *_args, **_kwargs: True, raising=False)
        monkeypatch.setattr(
            trade_executor,
            "_terminate_pid",
            lambda pid, force=False: terminate_calls.append((int(pid), bool(force))),
            raising=False,
        )
        monkeypatch.setattr(trade_executor, "_resolve_bridge_root", lambda: Path("/tmp/lean_bridge"), raising=False)

        cleaned = trade_executor.cleanup_terminal_run_processes(session, limit=10)
        session.commit()
        session.refresh(run)

        assert cleaned == 0
        assert terminate_calls == []
        lean_exec = dict((run.params or {}).get("lean_execution") or {})
        assert lean_exec.get("pid") == 55667
    finally:
        session.close()
