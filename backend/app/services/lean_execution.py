from __future__ import annotations

import json
import subprocess
from pathlib import Path

subprocess_run = subprocess.run


def build_execution_config(*, intent_path: str, brokerage: str) -> dict:
    return {
        "brokerage": brokerage,
        "execution-intent-path": intent_path,
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
