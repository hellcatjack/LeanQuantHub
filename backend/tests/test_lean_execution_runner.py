from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_execution
from app.core.config import settings


def test_launch_execution_calls_subprocess(monkeypatch, tmp_path):
    calls: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs

    monkeypatch.setattr(lean_execution, "subprocess_run", _fake_run, raising=False)

    lean_execution.launch_execution(
        config_path=str(tmp_path / "lean-config.json"),
    )
    assert "lean-config.json" in " ".join(calls["cmd"])
    assert calls["kwargs"].get("check") is False
    assert "env" in calls["kwargs"]


def test_launch_execution_async_returns_pid(monkeypatch, tmp_path):
    class _FakeProc:
        pid = 123

    def _fake_popen(cmd, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(lean_execution.subprocess, "Popen", _fake_popen)
    pid = lean_execution.launch_execution_async(config_path=str(tmp_path / "exec.json"))
    assert pid == 123


def test_launch_execution_async_sets_python_env(monkeypatch, tmp_path):
    captured = {}

    class _FakeProc:
        pid = 321

    def _fake_popen(cmd, cwd=None, env=None):
        captured["env"] = env
        return _FakeProc()

    monkeypatch.setattr(lean_execution.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(settings, "lean_python_venv", "/app/stocklean/.venv")
    monkeypatch.setattr(settings, "python_dll", "/app/stocklean/.venv/lib/libpython3.11.so")
    monkeypatch.setattr(settings, "dotnet_root", "/opt/dotnet")

    pid = lean_execution.launch_execution_async(config_path=str(tmp_path / "exec.json"))
    assert pid == 321
    env = captured.get("env") or {}
    assert env.get("PYTHONHOME") == "/app/stocklean/.venv"
    assert env.get("PYTHONNET_PYDLL") == "/app/stocklean/.venv/lib/libpython3.11.so"
    assert env.get("DOTNET_ROOT") == "/opt/dotnet"
    assert env.get("PATH", "").startswith("/opt/dotnet")
