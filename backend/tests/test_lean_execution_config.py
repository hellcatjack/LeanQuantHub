from pathlib import Path
import json
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_execution


def test_build_execution_config_includes_intent_path(tmp_path):
    config = lean_execution.build_execution_config(
        intent_path=str(tmp_path / "intent.json"),
        brokerage="InteractiveBrokersBrokerage",
        project_id=16,
        mode="paper",
    )
    assert config["execution-intent-path"].endswith("intent.json")
    assert "brokerage" in config


def test_build_execution_config_uses_execution_algorithm(tmp_path):
    config = lean_execution.build_execution_config(
        intent_path=str(tmp_path / "intent.json"),
        brokerage="InteractiveBrokersBrokerage",
        project_id=16,
        mode="paper",
    )
    assert config["algorithm-type-name"] == "LeanBridgeExecutionAlgorithm"

def test_execution_config_includes_bridge_result_handler():
    cfg = lean_execution.build_execution_config(
        intent_path="/tmp/intent.json",
        brokerage="InteractiveBrokersBrokerage",
        project_id=16,
        mode="paper",
    )
    assert cfg["result-handler"].endswith("LeanBridgeResultHandler")
    assert cfg["lean-bridge-output-dir"] == "/data/share/stock/data/lean_bridge"


def test_execution_config_includes_ib_client_id():
    cfg = lean_execution.build_execution_config(
        intent_path="/tmp/intent.json",
        brokerage="InteractiveBrokersBrokerage",
        project_id=16,
        mode="paper",
    )
    assert cfg["ib-client-id"] == 1016


def test_execution_config_leader_output_dir():
    cfg = lean_execution.build_execution_config(
        intent_path="/tmp/intent.json",
        brokerage="InteractiveBrokersBrokerage",
        project_id=16,
        mode="paper",
        client_id=1234,
        lean_bridge_output_dir="/tmp/lean_bridge_custom",
    )
    assert cfg["lean-bridge-output-dir"] == "/tmp/lean_bridge_custom"


def test_build_execution_config_merges_template(monkeypatch, tmp_path):
    template = tmp_path / "template.json"
    template.write_text(
        json.dumps(
            {
                "environment": "live-interactive",
                "algorithm-type-name": "LeanBridgeSmokeAlgorithm",
                "data-folder": "/data/share/stock/data/lean",
                "lean-bridge-output-dir": "/data/share/stock/data/lean_bridge",
                "ib-client-id": "101",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(lean_execution.settings, "lean_config_template", str(template))
    cfg = lean_execution.build_execution_config(
        intent_path=str(tmp_path / "intent.json"),
        brokerage="InteractiveBrokersBrokerage",
        project_id=16,
        mode="paper",
    )
    assert cfg["environment"] == "live-interactive"
    assert cfg["algorithm-type-name"] == "LeanBridgeExecutionAlgorithm"
    assert cfg["execution-intent-path"].endswith("intent.json")
    assert cfg["ib-client-id"] == 1016


def test_launch_execution_uses_launcher_path(monkeypatch, tmp_path):
    calls = {}

    def _fake_run(cmd, check=False, cwd=None):
        calls["cmd"] = cmd
        calls["cwd"] = cwd
        return None

    monkeypatch.setattr(lean_execution, "subprocess_run", _fake_run)
    monkeypatch.setattr(lean_execution.settings, "lean_launcher_path", str(tmp_path))
    monkeypatch.setattr(lean_execution.settings, "lean_launcher_dll", "QuantConnect.Lean.Launcher.dll")
    lean_execution.launch_execution(config_path="/tmp/exec.json")
    assert calls["cwd"] == str(tmp_path)
    assert calls["cmd"][1].endswith("QuantConnect.Lean.Launcher.dll")


def test_launch_execution_handles_launcher_path_file(monkeypatch, tmp_path):
    calls = {}

    def _fake_run(cmd, check=False, cwd=None):
        calls["cmd"] = cmd
        calls["cwd"] = cwd
        return None

    launcher_file = tmp_path / "QuantConnect.Lean.Launcher.csproj"
    launcher_file.write_text("fake", encoding="utf-8")
    monkeypatch.setattr(lean_execution, "subprocess_run", _fake_run)
    monkeypatch.setattr(lean_execution.settings, "lean_launcher_path", str(launcher_file))
    monkeypatch.setattr(lean_execution.settings, "lean_launcher_dll", "")
    lean_execution.launch_execution(config_path="/tmp/exec.json")
    assert calls["cwd"] == str(tmp_path)


def test_execution_config_overrides_backtesting_environment(monkeypatch, tmp_path):
    template = tmp_path / "template.json"
    template.write_text(
        json.dumps({"environment": "backtesting", "algorithm-type-name": "LeanBridgeSmokeAlgorithm"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(lean_execution.settings, "lean_config_template", str(template))
    cfg = lean_execution.build_execution_config(
        intent_path=str(tmp_path / "intent.json"),
        brokerage="InteractiveBrokersBrokerage",
        project_id=16,
        mode="paper",
    )
    assert cfg["environment"] == "live-interactive"


def test_template_fallback_overrides_empty_values(monkeypatch, tmp_path):
    template = tmp_path / "template.json"
    template.write_text(
        json.dumps(
            {
                "environment": "backtesting",
                "algorithm-language": "",
                "algorithm-location": "",
                "data-folder": "",
            }
        ),
        encoding="utf-8",
    )
    fallback = tmp_path / "fallback.json"
    fallback.write_text(
        json.dumps(
            {
                "algorithm-language": "CSharp",
                "algorithm-location": "/tmp/algorithm.dll",
                "data-folder": "/data/share/stock/data/lean",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(lean_execution.settings, "lean_config_template", str(template))
    monkeypatch.setattr(lean_execution, "_DEFAULT_CONFIG_TEMPLATE", fallback)
    cfg = lean_execution.build_execution_config(
        intent_path=str(tmp_path / "intent.json"),
        brokerage="InteractiveBrokersBrokerage",
        project_id=16,
        mode="paper",
    )
    assert cfg["algorithm-language"] == "CSharp"
    assert cfg["algorithm-location"] == "/tmp/algorithm.dll"
    assert cfg["data-folder"] == "/data/share/stock/data/lean"


def test_execution_config_forces_csharp_for_execution_algorithm(monkeypatch, tmp_path):
    template = tmp_path / "template.json"
    template.write_text(
        json.dumps({"algorithm-language": "Python", "algorithm-type-name": "LeanBridgeSmokeAlgorithm"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(lean_execution.settings, "lean_config_template", str(template))
    cfg = lean_execution.build_execution_config(
        intent_path=str(tmp_path / "intent.json"),
        brokerage="InteractiveBrokersBrokerage",
        project_id=16,
        mode="paper",
    )
    assert cfg["algorithm-language"] == "CSharp"


def test_launch_execution_prefers_bin_release_dll(monkeypatch, tmp_path):
    calls = {}

    def _fake_run(cmd, check=False, cwd=None):
        calls["cmd"] = cmd
        calls["cwd"] = cwd
        return None

    launcher_file = tmp_path / "QuantConnect.Lean.Launcher.csproj"
    launcher_file.write_text("fake", encoding="utf-8")
    dll_path = tmp_path / "bin" / "Release" / "QuantConnect.Lean.Launcher.dll"
    dll_path.parent.mkdir(parents=True, exist_ok=True)
    dll_path.write_text("fake", encoding="utf-8")
    monkeypatch.setattr(lean_execution, "subprocess_run", _fake_run)
    monkeypatch.setattr(lean_execution.settings, "lean_launcher_path", str(launcher_file))
    monkeypatch.setattr(lean_execution.settings, "lean_launcher_dll", "")
    lean_execution.launch_execution(config_path="/tmp/exec.json")
    assert calls["cmd"][1].endswith("bin/Release/QuantConnect.Lean.Launcher.dll")
