from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".." / "configs" / "lean_live_interactive_paper.json"


def test_lean_live_interactive_config_has_required_fields():
    assert CONFIG.exists(), "lean_live_interactive_paper.json should exist"
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))

    assert payload.get("environment") == "live-interactive"
    assert payload.get("result-handler") == "QuantConnect.Lean.Engine.Results.LeanBridgeResultHandler"
    assert payload.get("lean-bridge-output-dir") == "/data/share/stock/data/lean_bridge"

    assert payload.get("ib-host") == "192.168.1.31"
    assert payload.get("ib-port") == "7497"
    assert payload.get("ib-client-id") == "101"
    assert payload.get("ib-trading-mode") == "paper"

    assert payload.get("algorithm-type-name") == "LeanBridgeSmokeAlgorithm"
    assert payload.get("algorithm-location")
    assert payload.get("data-folder") == "/data/share/stock/data/lean"
