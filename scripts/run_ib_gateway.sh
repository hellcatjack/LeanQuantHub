#!/usr/bin/env bash
set -euo pipefail

IBC_PATH="${IBC_PATH:-$HOME/IBC}"
TWS_PATH="${TWS_PATH:-$HOME/Jts}"
TWS_SETTINGS_PATH="${TWS_SETTINGS_PATH:-}"
IBC_INI="${IBC_INI:-${IBC_PATH}/config.ini}"
IB_GATEWAY_MAJOR_VERSION="${IB_GATEWAY_MAJOR_VERSION:-1044}"
IB_GATEWAY_LOG_PATH="${IB_GATEWAY_LOG_PATH:-${IBC_PATH}/logs}"
IB_GATEWAY_ON_2FA_TIMEOUT="${IB_GATEWAY_ON_2FA_TIMEOUT:-exit}"
IB_GATEWAY_TRADING_MODE="${IB_GATEWAY_TRADING_MODE:-}"

if [[ ! -x "${IBC_PATH}/scripts/displaybannerandlaunch.sh" ]]; then
  echo "IBC launcher not found: ${IBC_PATH}/scripts/displaybannerandlaunch.sh" >&2
  exit 1
fi

export APP="GATEWAY"
export IBC_PATH
export TWS_PATH
export TWS_SETTINGS_PATH
export IBC_INI
export TWS_MAJOR_VRSN="${IB_GATEWAY_MAJOR_VERSION}"
export TWSUSERID="${IB_GATEWAY_USER:-}"
export TWSPASSWORD="${IB_GATEWAY_PASSWORD:-}"
export FIXUSERID="${IB_GATEWAY_FIX_USER:-}"
export FIXPASSWORD="${IB_GATEWAY_FIX_PASSWORD:-}"
export TRADING_MODE="${IB_GATEWAY_TRADING_MODE}"
export TWOFA_TIMEOUT_ACTION="${IB_GATEWAY_ON_2FA_TIMEOUT}"
export JAVA_PATH="${JAVA_PATH:-}"
export LOG_PATH="${IB_GATEWAY_LOG_PATH}"
export DISPLAY="${DISPLAY:-:99}"

exec "${IBC_PATH}/scripts/displaybannerandlaunch.sh"
