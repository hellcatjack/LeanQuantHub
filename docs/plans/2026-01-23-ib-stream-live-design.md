# IB 实时行情订阅（Live）设计

## 目标
- 在现有 `/api/ib/stream` API 基础上，接入 **真实 ibapi L1 行情订阅**。
- 行情持续落地到 `data/ib/stream/{SYMBOL}.json`，并维护 `_status.json`。
- 增加轻量回退：tick 过期或连接异常时用 snapshot 补写，保证 UI/风控有可用价格。
- 完成真实联通验证（IB Gateway/TWS 已配置）。

## 范围与假设
- 订阅来源：**决策快照 ID=3**（items.csv），上限 **50** 标的。
- 刷新间隔：**5 秒**（状态心跳与可选补写频率）。
- 数据源：IB（Paper/Live 视配置），训练/回测仍使用 Alpha。
- 不在本阶段实现期权、衍生品与高频分钟级策略。

## 架构与数据流（方案 B：实时 + 轻量回退）
1) `/api/ib/stream/start` 写入 `_config.json`：`project_id/decision_snapshot_id/max_symbols/refresh_interval_seconds/market_data_type/symbols`。
2) `IBStreamRunner` 读取 config，建立 ibapi 连接并订阅 L1 tick。
3) tick 回调：写入 `data/ib/stream/{SYMBOL}.json`（包含 `timestamp/source`）。
4) 每 5 秒写 `_status.json`：连接状态、订阅列表、心跳、错误数、最后错误。
5) 若 tick 过期或错误增多：触发 snapshot 补写并标记 `source=ib_snapshot`，状态切为 `degraded`。
6) 断线自动重连，恢复后状态切回 `connected`。

## 状态与回退策略
- `stale_seconds` 默认 15 秒：超过则回退 snapshot 补写一次。
- `_status.json` 字段建议：
  - `status`: `starting/connected/degraded/disconnected`
  - `last_heartbeat`, `subscribed_symbols`, `ib_error_count`, `last_error`
  - `market_data_type`
  - `degraded_since`（首次进入 degraded 的时间）
  - `last_snapshot_refresh`（最近一次回退时间）
- 回退只用于补齐最新价格，不替代持续订阅。

## 错误处理
- ibapi 连接失败/断线：记录 `last_error` 与 `ib_error_count`，状态 `disconnected`，进入重连。
- 单 symbol 订阅失败：跳过该标的，记录错误但不中断整个订阅。
- 写盘失败：记录错误，下一次 tick 重试；不终止进程。

## 验证与验收
**真实联通验证（必须）：**
1) 使用快照 ID=3 启动订阅（max 50，5s）。
2) `_status.json` 从 `starting → connected`。
3) 至少 3 个标的 `data/ib/stream/{SYMBOL}.json` 持续刷新，`source=ib_stream`。
4) 人为断开或停止 Gateway，`status=disconnected`；恢复后回到 `connected`。
5) stale 时触发 snapshot 补写，`source=ib_snapshot` 且 `last_snapshot_refresh` 更新。

## 风险与限制
- IB 行情权限、速率限制会影响稳定性；回退与限速策略是必需保障。
- 需要确认运行环境具备 ibapi 依赖与 Gateway/TWS 长连接可用性。

## 后续扩展
- 扩展 Level2/合约明细与更细粒度的节流控制。
- 推送告警：断线/降级/恢复。
