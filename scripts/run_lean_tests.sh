#!/usr/bin/env bash
set -euo pipefail

VENV_ROOT="${VENV_ROOT:-/app/stocklean/.venv}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"

export PYTHONHOME="$VENV_ROOT"
export PYTHONPATH="$VENV_ROOT/lib/python${PYTHON_VERSION}"
export PATH="$VENV_ROOT/bin:$PATH"

PROJECT_PATH="${1:-/app/stocklean/Lean_git/Tests/QuantConnect.Tests.csproj}"
if [[ "${1:-}" != "" ]]; then
  shift
fi

dotnet test "$PROJECT_PATH" "$@"
