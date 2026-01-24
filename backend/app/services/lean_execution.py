from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.core.config import settings

subprocess_run = subprocess.run


def _bridge_output_dir() -> str:
    base = settings.data_root or "/data/share/stock/data"
    return str(Path(base) / "lean_bridge")


def build_execution_config(*, intent_path: str, brokerage: str) -> dict:
    return {
        "brokerage": brokerage,
        "execution-intent-path": intent_path,
        "result-handler": "QuantConnect.Lean.Engine.Results.LeanBridgeResultHandler",
        "lean-bridge-output-dir": _bridge_output_dir(),
    }


def launch_execution(*, config_path: str) -> None:
    cmd = ["dotnet", "QuantConnect.Lean.Launcher.dll", "--config", config_path]
    subprocess_run(cmd, check=False)


def ingest_execution_events(path: str) -> None:
    events = json.loads(Path(path).read_text(encoding="utf-8"))
    apply_execution_events(events)


def apply_execution_events(events: list[dict]) -> None:
    # TODO: update trade_orders / trade_fills in DB
    return None
