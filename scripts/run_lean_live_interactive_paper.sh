#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONNET_PYDLL="/home/hellcat/.pyenv/versions/3.10.19/lib/libpython3.10.so"
PYTHONHOME="/home/hellcat/.pyenv/versions/3.10.19"

export PYTHONNET_PYDLL
export PYTHONHOME

CONFIG="$ROOT_DIR/configs/lean_live_interactive_paper.json"
LAUNCHER="/app/stocklean/Lean_git/Launcher/bin/Release/QuantConnect.Lean.Launcher.dll"

exec dotnet "$LAUNCHER" --config "$CONFIG"
