# IB Gateway CPU Spike Recovery Hardening Design

## Background
On April 2, 2026 from 09:21 to 09:30 EDT, StockLean triggered repeated recovery escalation in the IB Gateway path. The sequence ended with an IB Gateway restart, followed by Lean bridge account download and restoration of 79 subscriptions, which produced IB API rate limiting and a CPU/log burst.

## Goal
- Make `gateway_restart` non-blocking so the watchdog is not killed by its own `oneshot` timeout.
- Persist `gateway_restarting` state immediately before the restart is handed off to systemd.
- Batch subscription restoration after reconnect instead of replaying all subscriptions in a single burst.
- Reduce noisy IB farm OK/idle logs.

## Design
1. Change watchdog restart execution to `systemctl --user restart --no-block ...` and persist runtime health before invoking systemd.
2. Batch restored subscriptions in the IB brokerage implementation using configurable batch size and inter-batch delay.
3. Replace per-symbol recovery TRACE spam with batch summary logs.
4. Downgrade `2104/2106/2107/2108/2158` to informational logging while preserving real disconnect error handling.

## Files
- `scripts/ib_gateway_watchdog.py`
- `backend/tests/test_ib_gateway_recovery.py`
- `Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/InteractiveBrokersBrokerage.cs`
- `Lean_git/Brokerages/InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage.Tests/InteractiveBrokersBrokerageAdditionalTests.cs`
