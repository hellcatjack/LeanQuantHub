#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${STOCKLEAN_ROOT:-/app/stocklean}"
BACKEND_URL="${STOCKLEAN_BACKEND_URL:-http://localhost:8021}"
PROJECT_ID="${STOCKLEAN_PROJECT_ID:-${1:-}}"

if [ -z "${PROJECT_ID}" ]; then
  if [ -d "${ROOT_DIR}/artifacts" ]; then
    latest_project="$(ls -td "${ROOT_DIR}"/artifacts/project_* 2>/dev/null | head -n 1 || true)"
    if [ -n "${latest_project}" ]; then
      PROJECT_ID="${latest_project##*project_}"
    fi
  fi
fi

if [ -z "${PROJECT_ID}" ]; then
  echo "Missing project id. Set STOCKLEAN_PROJECT_ID or pass project id as the first argument."
  exit 1
fi

payload="{\"project_id\": ${PROJECT_ID}}"

curl -sS -X POST "${BACKEND_URL}/api/automation/weekly-jobs" \
  -H "Content-Type: application/json" \
  -d "${payload}"
echo
