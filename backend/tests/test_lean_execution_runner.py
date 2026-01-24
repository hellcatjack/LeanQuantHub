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
