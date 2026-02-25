#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${IB_GATEWAY_SERVICE_NAME:-stocklean-ibgateway.service}"
HOST="${IB_GATEWAY_HOST:-127.0.0.1}"
PORT="${IB_GATEWAY_PORT:-4002}"
MAX_ESTAB="${IB_GATEWAY_WATCHDOG_MAX_ESTAB:-40}"
MAX_CLOSE_WAIT="${IB_GATEWAY_WATCHDOG_MAX_CLOSE_WAIT:-20}"
FAIL_THRESHOLD="${IB_GATEWAY_WATCHDOG_FAIL_THRESHOLD:-3}"
RESTART_COOLDOWN_SECONDS="${IB_GATEWAY_WATCHDOG_RESTART_COOLDOWN_SECONDS:-900}"
STATE_FILE="${IB_GATEWAY_WATCHDOG_STATE_FILE:-/tmp/stocklean-ibgateway-watchdog.state}"

failures=0
last_restart_epoch=0
if [[ -f "${STATE_FILE}" ]]; then
  while IFS='=' read -r key value; do
    case "${key}" in
      failures) failures="${value}" ;;
      last_restart_epoch) last_restart_epoch="${value}" ;;
    esac
  done <"${STATE_FILE}"
fi

reasons=()

if ! systemctl --user is-active --quiet "${SERVICE_NAME}"; then
  reasons+=("service_inactive")
fi

if ! pgrep -f "ibcalpha\\.ibc\\.IbcGateway" >/dev/null 2>&1; then
  reasons+=("gateway_process_missing")
fi

if ! timeout 2 bash -lc "</dev/tcp/${HOST}/${PORT}" >/dev/null 2>&1; then
  reasons+=("api_port_unreachable:${HOST}:${PORT}")
fi

socket_snapshot="$(ss -tan "( sport = :${PORT} or dport = :${PORT} )" || true)"
estab_count="$(printf "%s\n" "${socket_snapshot}" | awk '/ESTAB/ {c+=1} END {print c+0}')"
close_wait_count="$(printf "%s\n" "${socket_snapshot}" | awk '/CLOSE-WAIT/ {c+=1} END {print c+0}')"

if (( estab_count > MAX_ESTAB )); then
  reasons+=("estab_overflow:${estab_count}")
fi

if (( close_wait_count > MAX_CLOSE_WAIT )); then
  reasons+=("close_wait_overflow:${close_wait_count}")
fi

if (( ${#reasons[@]} == 0 )); then
  cat >"${STATE_FILE}" <<EOF
failures=0
last_restart_epoch=${last_restart_epoch}
EOF
  echo "ib_gateway_watchdog: healthy (estab=${estab_count}, close_wait=${close_wait_count})"
  exit 0
fi

failures=$((failures + 1))
now_epoch="$(date +%s)"
cat >"${STATE_FILE}" <<EOF
failures=${failures}
last_restart_epoch=${last_restart_epoch}
EOF

reason_text="$(IFS=,; echo "${reasons[*]}")"
echo "ib_gateway_watchdog: degraded failures=${failures} reasons=${reason_text}"

if (( failures < FAIL_THRESHOLD )); then
  exit 0
fi

if (( now_epoch - last_restart_epoch < RESTART_COOLDOWN_SECONDS )); then
  echo "ib_gateway_watchdog: restart cooldown active, skip restart"
  exit 0
fi

echo "ib_gateway_watchdog: restarting ${SERVICE_NAME}"
systemctl --user restart "${SERVICE_NAME}"

cat >"${STATE_FILE}" <<EOF
failures=0
last_restart_epoch=${now_epoch}
EOF
