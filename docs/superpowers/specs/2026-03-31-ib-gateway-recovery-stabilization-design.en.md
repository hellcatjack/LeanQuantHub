# IB Gateway Recovery Stabilization Design

## Background
The `2026-03-31 15:35` to `15:45 EDT` CPU spike was driven by the IB Gateway recovery chain repeatedly escalating from `bridge_refresh` to `leader_restart` to `gateway_restart`, which amplified Lean bridge reconnect work, account re-download, subscription restoration, and TRACE log volume.

## Goal
- Reduce false-positive recovery escalations caused by transient probe latency.
- Add a recovery quiet period after `leader_restart` and `gateway_restart`.
- Require business-level stale signals in addition to probe failures before marking the bridge as degraded.

## Design
1. Raise default watchdog probe thresholds to `1.5s` soft and `5.0s` hard.
2. Add `ib_gateway_recovery_quiet_period_seconds = 240`.
3. Change `build_gateway_runtime_health()` so probe failures alone do not produce `bridge_degraded`; snapshot staleness or stuck commands must also be present unless the bridge itself is stale.
4. During the quiet period after a restart action, suppress further escalations and keep the system in a recovery-oriented blocked state until either health returns or the quiet period expires.

## Files
- `backend/app/core/config.py`
- `backend/app/services/ib_gateway_runtime.py`
- `scripts/ib_gateway_watchdog.py`
- `backend/tests/test_ib_gateway_runtime.py`
- `backend/tests/test_ib_gateway_recovery.py`
