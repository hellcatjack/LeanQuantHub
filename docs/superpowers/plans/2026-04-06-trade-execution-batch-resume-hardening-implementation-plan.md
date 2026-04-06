# 实盘交易分批提交与 Partial 自动续跑实施计划

> 执行说明：本计划覆盖本轮“批量 leader 提交 + partial 自动续跑”加固。按任务完成后必须运行对应测试，禁止跳过失败测试直接改实现。

## 目标
修复大批量交易批次在 `leader_submit` 路径上的过早超时问题，并在 `partial` 终态后自动生成剩余 delta 的续跑批次，减少人工介入。

## 架构概要
- `execute_trade_run()` 负责初始化 `leader_command` 批次元数据并只分发首批订单。
- `refresh_trade_run_status()` 负责推进后续批次、判定终态，并在满足条件时自动创建并执行子 run。
- 子 run 继续复用现有“基于当前持仓 + decision snapshot 重建 rebalance orders”的执行路径。

## 任务 1：leader_submit 分批提交

涉及文件：
- `backend/app/services/trade_executor.py`
- `backend/tests/test_trade_executor_leader_submit.py`

- [x] 为 `execute_trade_run()` 增加失败测试，要求 leader 路径只提交首批订单。
- [x] 为 `refresh_trade_run_status()` 增加失败测试，要求当前批次清空后推进下一批。
- [x] 在 `trade_executor.py` 中加入批量元数据和 `_dispatch_next_leader_submit_batch()`。
- [x] 将 `execute_trade_run()` 的 leader 提交流程改成“初始化 + 首批分发”。
- [x] 在 `refresh_trade_run_status()` 中接入“当前批次 cleared -> 推进下一批”逻辑。
- [x] 跑最小测试集，确认分批提交链路通过。

## 任务 2：leader pending 超时批次化

涉及文件：
- `backend/app/services/trade_executor.py`
- `backend/tests/test_trade_executor_leader_submit.py`

- [x] 增加失败测试，覆盖大批量 leader 批次在合理等待窗口内不应被过早超时。
- [x] 将 pending timeout 从固定 `12s` 扩展为基础值 + 批次线性放宽，上限封顶。
- [x] 优先基于当前批次大小/订单列表估算超时，而不是使用全量订单数。
- [x] 重新运行针对性测试并确认通过。

## 任务 3：partial 自动续跑

涉及文件：
- `backend/app/services/trade_executor.py`
- `backend/tests/test_trade_run_partial_auto_resume.py`

- [x] 为 `partial + filled + skipped` 场景增加失败测试，要求自动创建并执行子 run。
- [x] 为 `partial + rejected` 场景增加失败测试，要求不自动续跑。
- [x] 在 `trade_executor.py` 中增加自动续跑策略、参数净化和元数据写回。
- [x] 在终态收口点先提交父 run，再触发 `_maybe_auto_resume_partial_run()`。
- [x] 重新运行 `test_trade_run_partial_auto_resume.py`，确认通过。

## 任务 4：回归验证

涉及文件：
- 无新增业务文件

- [x] 运行 `pytest backend/tests/test_trade_executor_leader_submit.py backend/tests/test_trade_open_orders_sync.py backend/tests/test_trade_executor_runtime_error_detection.py backend/tests/test_trade_run_partial_auto_resume.py -q`
- [x] 运行 `pytest backend/tests/test_trade_run_create_idempotent.py backend/tests/test_trade_executor_snapshot_guard.py -q`
- [x] 重启 `stocklean-backend` 并验证服务状态正常。
- [x] 记录本轮未处理项：`live` 健康门禁、未知状态机重构、fallback 高置信度收敛。

## 本轮未处理项

1. `live` 交易前的 Gateway/Bridge 健康门禁。
2. 将 `SKIPPED` / `missing_from_open_orders` 重构为更高置信度的未知状态机。
3. `short_lived_fallback` 后续的高置信度收敛与自动差异恢复。
