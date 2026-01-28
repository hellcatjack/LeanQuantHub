from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_execution


def test_launch_execution_calls_subprocess(monkeypatch, tmp_path):
    calls: dict[str, list[str]] = {}

    def _fake_run(cmd, check):
        calls["cmd"] = cmd

    monkeypatch.setattr(lean_execution, "subprocess_run", _fake_run, raising=False)

    lean_execution.launch_execution(
        config_path=str(tmp_path / "lean-config.json"),
    )
    assert "lean-config.json" in " ".join(calls["cmd"])


def test_launch_execution_async_returns_pid(monkeypatch, tmp_path):
    class _FakeProc:
        pid = 123

    def _fake_popen(cmd, cwd=None):
        return _FakeProc()

    monkeypatch.setattr(lean_execution.subprocess, "Popen", _fake_popen)
    pid = lean_execution.launch_execution_async(config_path=str(tmp_path / "exec.json"))
    assert pid == 123
