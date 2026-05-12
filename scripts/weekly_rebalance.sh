#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${STOCKLEAN_ROOT:-/app/stocklean}"
BACKEND_URL="${STOCKLEAN_BACKEND_URL:-http://127.0.0.1:8021}"
PHASE="${1:-${STOCKLEAN_WEEKLY_REBALANCE_PHASE:-prepare}}"
PROJECT_ID="${STOCKLEAN_PROJECT_ID:-${2:-}}"
FORCE="${STOCKLEAN_WEEKLY_REBALANCE_FORCE:-false}"
DRY_RUN="${STOCKLEAN_WEEKLY_REBALANCE_DRY_RUN:-false}"

if [ -z "${PROJECT_ID}" ]; then
  if [ -d "${ROOT_DIR}/artifacts" ]; then
    latest_project="$(ls -td "${ROOT_DIR}"/artifacts/project_* 2>/dev/null | head -n 1 || true)"
    if [ -n "${latest_project}" ]; then
      PROJECT_ID="${latest_project##*project_}"
    fi
  fi
fi

if [ -z "${PROJECT_ID}" ]; then
  echo "Missing project id. Set STOCKLEAN_PROJECT_ID or pass project id as the second argument."
  exit 1
fi

case "${PHASE}" in
  prepare|execute)
    ;;
  *)
    echo "Invalid phase: ${PHASE}. Expected prepare or execute."
    exit 2
    ;;
esac

payload="{\"project_id\": ${PROJECT_ID}, \"force\": ${FORCE}, \"dry_run\": ${DRY_RUN}}"

curl -sS -X POST "${BACKEND_URL}/api/automation/weekly-rebalance/${PHASE}" \
  -H "Content-Type: application/json" \
  -d "${payload}"
echo
