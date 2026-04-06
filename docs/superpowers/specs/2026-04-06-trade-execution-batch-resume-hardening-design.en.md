# Trade Execution Batch Submission and Partial Auto-Resume Hardening Design

## Background
During investigation of paper trade run `1171`, StockLean submitted a `37`-order rebalance through the leader path. The first `7` orders were acknowledged and filled, while the remainder were prematurely classified as `leader_submit_pending_timeout`, triggering short-lived fallback and eventually collapsing into `SKIPPED` orders.

The underlying problem was not strategy logic or explicit IB rejection. It was an execution-path mismatch:

1. `leader_submit` progressed sequentially, but timeout handling assumed a small single-order workflow.
2. A terminal `partial` run had no built-in follow-up mechanism to regenerate and execute the remaining delta from current holdings.

## Goals

1. Convert `leader_submit` from one-shot bulk dispatch into controlled batch dispatch.
2. Keep the existing `leader_command -> fallback` architecture, but scope pending timeout checks to the current batch.
3. Auto-create and execute a follow-up delta run when a terminal `partial` result satisfies high-confidence criteria.
4. Ensure follow-up execution rebuilds from current holdings instead of replaying stale order intents.
5. Preserve strategy semantics, backtest semantics, and existing frontend behavior.

## Non-Goals

1. No live-only health gate in this round.
2. No redesign of `SKIPPED` into a richer uncertainty state machine.
3. No removal of short-lived fallback itself; this round only reduces false fallback triggers.
4. No frontend changes.

## Design

### 1. Controlled leader batching
`execute_trade_run()` now initializes leader execution metadata and dispatches only the first batch. `refresh_trade_run_status()` dispatches the next batch only after the current batch clears.

Default batch size: `6`

Tracked metadata includes:
- `batch_size`
- `total_orders`
- `dispatched_orders`
- `dispatched_batches`
- `current_batch_order_ids`
- `current_batch_size`
- `current_batch_submitted_at`
- `command_history`

### 2. Batch-aware pending timeout
Timeout is no longer a flat `12s` across the full run. It is now scaled from the active batch:
- base: `12s`
- add `3s` per order
- cap: `90s`

This avoids timing out orders that have not even reached the brokerage path yet.

### 3. Automatic follow-up for partial completion
When a run reaches terminal `partial` and all of the following hold:
- some fills exist
- no rejections exist
- skipped/cancelled orders exist
- a decision snapshot exists
- max attempts not exceeded
- no child run already queued

The system:
1. commits the parent terminal state and summary
2. creates a child `TradeRun(status=queued)`
3. sanitizes inherited params
4. immediately calls `execute_trade_run(child.id)`

Because the child run starts without persisted orders, the normal rebalance builder reconstructs a delta from current holdings plus the same decision snapshot.

### 4. Sanitized follow-up params
Runtime-only fields are removed before creating the child run, including leader/fallback runtime state, prior completion summaries, intent paths, baselines, and pending timeout traces.

The child receives:
- `auto_resume_parent_run_id`
- `auto_resume_root_run_id`
- `auto_resume_attempt`
- `auto_resume_reason=partial_remaining`

The parent receives `params.auto_resume` metadata such as child run id, attempt, summary, queue timestamp, and execution result/error.

## Test Strategy

### Leader batching
1. execution submits only the first batch
2. status refresh dispatches the next batch after the previous batch clears
3. large leader batches remain running within the scaled timeout window

### Partial auto-resume
1. `filled + skipped` partial run auto-queues and executes a child run
2. partial run with rejections does not auto-resume
3. child run contains the `auto_resume_*` metadata
4. parent terminal state is committed before child execution begins

## Acceptance Criteria

1. `leader_submit` no longer pushes `30+` orders in one burst.
2. Large batches are not prematurely classified as pending timeout.
3. Terminal partial runs can automatically queue and execute a follow-up delta run.
4. Follow-up execution rebuilds from current holdings instead of replaying stale intents.
5. New tests pass together with the related regression suite.
