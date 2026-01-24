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
    )
    assert config["execution-intent-path"].endswith("intent.json")
    assert "brokerage" in config
