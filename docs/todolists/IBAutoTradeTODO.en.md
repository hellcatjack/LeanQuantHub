# IBAuto Trade TODO (English Companion)

> This is the English companion of `docs/todolists/IBAutoTradeTODO.md`. It is a concise summary; refer to the Chinese version for full details.

## Summary
- This TODO list tracks tasks, sequencing, and validation for **IBAuto Trade TODO**.
- Use it to plan implementation order, testing, and operational checks.

## Current Progress (MVP)
- ✅ Completed: order event capture (IBRequestSession), live order submission MVP (submit_orders_live), trade executor routes to live branch.
- ✅ Completed: basic L1 market stream (snapshot polling), stream cache under `data/ib/stream/`, heartbeat/error counters.
- ⏳ Remaining: full risk controls, alerts, scheduling, reconciliation, and production runbooks.
