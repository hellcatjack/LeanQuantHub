# 每周自动调仓设计

## 背景

目标是在每周一自动完成三件事：

1. 开盘前运行数据页 PreTrade 周度检查。
2. PreTrade 成功后生成本周待执行的交易批次。
3. 开盘后自动执行该批次，并通过现有 Telegram 通道发送结果。

现有系统已经具备 PreTrade、DecisionSnapshot、TradeRun、交易执行、Telegram 配置和 user systemd 服务。新实现复用这些能力，不新增交易绕行路径。

## 方案选择

推荐方案：两阶段自动调仓。

- `prepare` 阶段：周一 08:00 ET 运行 PreTrade，但禁用 `market_snapshot` 和 `trade_execute`。该阶段负责数据检查、PIT 周度数据、训练/评分、决策快照和 queued TradeRun 创建。
- `execute` 阶段：周一 09:35 ET 检查今天是交易日且 RTH 已开盘，查找同一 ISO 周内成功的 prepare run，执行其关联 TradeRun。
- 通知：每个阶段结束后通过 `PreTradeSettings.telegram_bot_token/chat_id` 对应的既有 Telegram 通道发送摘要。

备选方案 1 是把 `trade_execute` 留在 PreTrade 内部等待开盘，这会让一个 PreTrade 任务跨越开盘长时间阻塞，并且异常恢复边界不清晰。备选方案 2 是只做 cron 脚本直接调用现有 API，不新增后端编排层；这会让幂等、开盘保护和测试覆盖不足。因此采用后端服务 + systemd timer 的两阶段实现。

## 架构

新增 `backend/app/services/weekly_rebalance.py` 作为编排层，提供：

- `prepare_weekly_rebalance(project_id, force=False)`：创建或复用本周 PreTrade run，运行 pre-open 步骤，记录 `weekly_rebalance` 元数据。
- `execute_weekly_rebalance(project_id, dry_run=False, force=False)`：复用本周成功 PreTrade run，验证交易日和开盘状态，执行关联 TradeRun。
- 幂等查找：同一 project + ISO week 内已有 prepare/execution 结果时默认复用，不重复建批次、不重复提交订单。
- 通知摘要：统一构造 Telegram 文案，并复用 `notify_trade_alert` 发送。

`backend/app/routes/automation.py` 增加两个 API：

- `POST /api/automation/weekly-rebalance/prepare`
- `POST /api/automation/weekly-rebalance/execute`

部署层新增：

- `scripts/weekly_rebalance.sh`
- `deploy/systemd/stocklean-weekly-rebalance-prepare.service`
- `deploy/systemd/stocklean-weekly-rebalance-prepare.timer`
- `deploy/systemd/stocklean-weekly-rebalance-execute.service`
- `deploy/systemd/stocklean-weekly-rebalance-execute.timer`

## 数据与状态

不新增数据库表。状态写入现有 JSON 字段：

- `PreTradeRun.params.weekly_rebalance`
- `TradeRun.params.weekly_rebalance`

关键字段：

- `week_key`: ISO 周，例如 `2026-W20`
- `phase`: `prepare` 或 `execute`
- `prepared_at`, `executed_at`
- `pretrade_run_id`, `decision_snapshot_id`, `trade_run_id`
- `status`, `message`

## 风控与错误处理

- 非周一、非交易日、未开盘时自动跳过，除非显式 `force=true`。
- prepare 阶段已有 active/success run 时复用，避免重复数据任务。
- execute 阶段只执行 queued TradeRun；running/done/blocked/failed 默认只通知状态，不强制重试。
- 真正下单仍走 `execute_trade_run()`，继续使用现有现金保护、IB Gateway block state、guard precheck、Lean leader 提交和自动恢复。

## 验收标准

- 周一 08:00 ET timer 自动触发 prepare，成功后创建 PreTradeRun 和 queued TradeRun。
- 周一 09:35 ET timer 自动触发 execute，只在交易日且开盘后执行。
- 同一周重复触发不会重复创建 PreTradeRun 或重复执行 TradeRun。
- prepare 成功、prepare 失败、execute 成功/提交、execute 被阻塞都会发送 Telegram 摘要。
- 单元测试覆盖 prepare 建批次、prepare 幂等、execute 开盘保护、execute 执行和通知。
