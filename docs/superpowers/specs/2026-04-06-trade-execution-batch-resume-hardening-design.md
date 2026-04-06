# 实盘交易分批提交与 Partial 自动续跑加固设计

## 背景
`2026-04-06` 排查 `paper` 批次 `1171` 时发现，系统在 `37` 笔订单的大批量提交场景下，前 `7` 笔成交后，其余订单被过早判定为 `leader_submit_pending_timeout`，随后触发 `short_lived_fallback`，最终大量订单被收敛为 `SKIPPED`。

问题的核心不是策略错误，也不是 IB 明确拒单，而是执行链路把“慢响应中的顺序提交”错误地当成“提交失败”。旧实现存在两个结构性缺口：

1. `leader_submit` 以顺序方式推进，但超时判断是按单笔单的固定阈值设计。
2. `partial` 运行结束后没有自动把“剩余 delta”重新生成并提交，只能靠操作员手工观察和补跑。

## 目标

1. 将 `leader_submit` 从“一次性提交整批订单”改为“受控分批提交”。
2. 保留现有 `leader_command -> fallback` 路径，但让 pending 超时只针对当前批次，而不是整批订单。
3. 当 `TradeRun` 以 `partial` 结束且满足高置信度条件时，自动创建后续 delta 批次并立即执行。
4. 确保续跑基于当前持仓重建订单，而不是盲目重放历史 intent。
5. 不改变策略层风险判断、不改变回测语义、不修改前端页面。

## 非目标

1. 本轮不实现 `live` 专用健康门禁。
2. 本轮不把未知状态从 `SKIPPED` 重构为新的中间状态机。
3. 本轮不改变 `short_lived_fallback` 的存在方式，只修正其过早触发的概率。
4. 本轮不处理前端提示和操作按钮。

## 方案

### 1. leader_submit 改为固定小批量推进
在 [trade_executor.py](/app/stocklean/backend/app/services/trade_executor.py) 内增加批量提交协调逻辑：

- 默认批大小：`6`
- `execute_trade_run()` 在 `leader_command` 模式下不再一次性调用 `_submit_run_orders_via_leader()` 提交全部订单。
- 改为先初始化 `lean_execution` 元数据，再仅分发第一批。
- `refresh_trade_run_status()` 每次刷新时，如果当前批次的 pending 已经清空，自动分发下一批。

新增元数据：
- `lean_execution.batch_size`
- `lean_execution.total_orders`
- `lean_execution.dispatched_orders`
- `lean_execution.dispatched_batches`
- `lean_execution.current_batch_order_ids`
- `lean_execution.current_batch_size`
- `lean_execution.current_batch_submitted_at`
- `lean_execution.command_history`

这样可以把一个 `30+` 笔的大单拆成多次可观测的小批次，并把 pending 判断限定到“当前批次是否卡住”。

### 2. pending 超时按当前批次动态放宽
保留基础超时阈值，但不再把整批未确认订单共用一个固定 `12s`。

规则：
- 基础阈值：`12s`
- 每多一笔再加：`3s`
- 最大阈值：`90s`
- 当前实现优先使用 `current_batch_size/current_batch_order_ids` 估算阈值，而不是全量 `orders` 数量

这样可以避免大批量订单仅因为还没轮到提交或回执，就被提前打成超时。

### 3. partial 终态后自动续跑剩余 delta
在 `refresh_trade_run_status()` 的终态收口点增加自动续跑逻辑：

触发条件：
- `run.status == partial`
- `summary.filled > 0`
- `summary.rejected == 0`
- `summary.cancelled + summary.skipped > 0`
- `run.decision_snapshot_id` 存在
- 未超过最大尝试次数
- 当前父 run 还没有挂过 `auto_resume.child_run_id`

动作：
1. 先提交父 run 终态和 `completion_summary`
2. 创建一个新的 `TradeRun(status=queued)`
3. 子 run 参数继承父 run 的执行配置，但清理运行态字段
4. 立即调用 `execute_trade_run(child_run.id)`

因为子 run 不预生成历史订单，所以 `execute_trade_run()` 会走现有的“按当前持仓 + 当前 snapshot 重新建单”的路径，自然形成 delta 续跑。

### 4. 子 run 参数净化
为了避免把父 run 的脏运行态直接带进下一次执行，需要移除：

- `order_intent_path`
- `execution_params_path`
- `price_map`
- `positions_baseline`
- `builder`
- `completion_summary`
- `lean_execution`
- `leader_submit_fallback`
- `leader_submit_runtime_fallback`
- `submit_command_pending_timeout`
- `already_held_orders`
- `risk_blocked`
- `guard_blocked`
- 其他纯运行态痕迹

保留：
- `strategy_snapshot`
- `risk/risk_overrides`
- `auto_recovery`
- 执行模式和必要的调度上下文

新增续跑元数据：
- `auto_resume_parent_run_id`
- `auto_resume_root_run_id`
- `auto_resume_attempt`
- `auto_resume_reason=partial_remaining`

父 run 的 `params.auto_resume` 中记录：
- `child_run_id`
- `attempt`
- `max_attempts`
- `summary`
- `queued_at`
- `execute_status` 或 `execute_error`

## 影响范围

### 修改文件
- `backend/app/services/trade_executor.py`
- `backend/tests/test_trade_executor_leader_submit.py`
- `backend/tests/test_trade_run_partial_auto_resume.py`

### 需要验证但未修改的路径
- `execute_trade_run()` 的“无预生成订单 -> 当前持仓重建 delta”逻辑
- `refresh_trade_run_status()` 的终态收口和 stalled 恢复逻辑

## 测试策略

### leader_submit 分批
1. 执行时只分发第一批，不一次性提交全部订单。
2. 前一批 pending 清空后，刷新状态会推进下一批。
3. 大批量 leader 批次在扩展阈值内不应过早触发 timeout。

### partial 自动续跑
1. `filled + skipped` 的 `partial` run 会自动创建并执行子 run。
2. 含 `rejected` 的 `partial` run 不会自动续跑。
3. 子 run 会携带 `auto_resume_*` 元数据。
4. 父 run 的终态和 `completion_summary` 必须先落库，再进行续跑。

## 验收标准

1. `leader_submit` 不再一次性提交 `30+` 笔订单。
2. 大批量提交在合理等待窗口内不会被误判为 `leader_submit_pending_timeout`。
3. `partial` run 结束后，系统可自动排队并执行下一次 delta 续跑。
4. 续跑基于当前持仓重建目标，避免重复提交已成交的风险资产。
5. 新增测试先失败后通过，相关回归集全部通过。
