from pathlib import Path
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
