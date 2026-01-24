from __future__ import annotations

import subprocess

subprocess_run = subprocess.run


def build_execution_config(*, intent_path: str, brokerage: str) -> dict:
    return {
        "brokerage": brokerage,
        "execution-intent-path": intent_path,
    }


def launch_execution(*, config_path: str) -> None:
    cmd = ["dotnet", "QuantConnect.Lean.Launcher.dll", "--config", config_path]
    subprocess_run(cmd, check=False)
