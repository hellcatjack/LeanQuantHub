# IB 自动化交易闭环（Paper + Live 真连通）设计与计划

> 目标：在 IB API 可用前提下，完成 **Paper + Live** 实盘闭环（数据→信号→风控→执行→监控），确保单实例、可追溯、可回滚。

## 1. 背景与范围
- 基于 `docs/todolists/IBAutoTradeTODO.md` 的首期目标：IB PRO 账户、IB 数据源、周频调仓闭环。
- 交易执行 **优先使用 IB 行情**（streaming），训练/回测仍使用 Alpha。
- 首期不覆盖期权与高频策略。

## 2. 当前现状与差距评审
### 已具备
- LiveTrade 页面与 IB 配置/探测/合约缓存/历史补齐接口。
- TradeRun/TradeOrder/TradeFill 基础表与 Mock 执行闭环。
- 预交易风控与 TradeGuard 评估接口。

### 关键差距
- **真实下单缺失**：执行仍走 `submit_orders_mock`，Live/Paper 未接真实 IB。
- **行情 streaming 缺失**：仅写 `_status.json`，无常驻订阅与心跳，且未加锁。
- **盘中风控未调度**：只有手动评估接口，缺少周期性评估与自动阻断。
- **回退机制与告警不足**：回退与 Telegram 告警未形成闭环。

## 3. 设计目标与原则
- **Paper + Live 真连通**：同一执行器，按账号与模式切换。
- **单实例执行**：锁 + 心跳，避免多副本并发下单/订阅。
- **可追溯可回放**：快照、参数、订单、成交、告警可审计。
- **风控优先**：预交易 + 盘中，触发即阻断并告警。
- **数据一致**：交易/风控估值统一读取 `data/ib/stream`。

## 4. 架构与数据流
```
PreTradeRun -> DecisionSnapshot -> TradeRun(queued)
  -> OrderBuilder -> RiskEngine(pre)
  -> IBOrderExecutor (Paper/Live)
  -> TradeOrder/TradeFill 回写
  -> TradeRun 状态更新

IBStreamRunner (常驻)
  -> data/ib/stream/{symbol}.json
  -> data/ib/stream/_status.json
```
- 交易执行层（TradeExecutor）只做编排；真实下单封装在 IBOrderExecutor。
- 行情层由 IBStreamRunner 维护订阅与写入；断线降级至 snapshot/history。

## 5. 模块拆分与职责
### 5.1 IBStreamRunner
- 负责订阅与写入 `data/ib/stream`。
- 订阅集合：决策快照优先，项目成分为回退；支持 `max_symbols`。
- 锁：`JobLock("ib_stream")`，防止多副本并发订阅。
- 状态：`connected/degraded/disconnected`，写 `_status.json`。

### 5.2 IBOrderExecutor
- 订单提交：MKT/LMT；监听 `orderStatus/execDetails`。
- 回写：TradeOrder 状态机、TradeFill 逐笔累积、均价更新。
- 幂等：`clientOrderId = run_id:symbol:side[:snapshot_id]`。
- Paper/Live 切换：通过 IBSettings.mode + account_id。

### 5.3 TradeExecutor
- 编排：快照 -> 订单 -> 风控 -> 执行 -> 状态更新。
- 执行前检查：IB 连接与 TradeGuard 状态。

### 5.4 TradeGuard
- 盘中评估：定时评估（如 1-5 分钟），阈值触发即 `halted`。
- 估值：优先 stream，超时降级 snapshot/history，标记来源。

## 6. 错误处理与回退
- 连接不可用：TradeRun 标记 `blocked`，原因 `connection_unavailable`。
- 行情缺失：订单 `REJECTED`，记录 `market_data_error`。
- 下单失败：订单 `REJECTED`，记录 `reject_reason`，批次 `partial/failed`。
- 回退：执行失败或行情异常时，回退到上次成功决策快照，并记录回退目标。

## 7. 数据与存储
- `data/ib/stream/{symbol}.json` + `_status.json`
- DB：
  - `trade_runs`、`trade_orders`、`trade_fills`（已存在）
  - `trade_guard_state`（已存在）
  - 可选：`trade_runs` 增加 `execution_mode` / `account_id` 记录（如需）

## 8. 监控与告警
- UI：连接状态、stream 状态、订阅数量、最近批次/订单/成交。
- Telegram：断线、下单失败、风控触发、回退事件。

## 9. 测试与验收
- 单测：订单生成、风控、幂等、部分成交、stream 状态机。
- 集成：Mock IB 下单+回写、stream 降级、锁冲突。
- 端到端：PreTrade -> TradeRun -> 执行 -> UI 展示。

**验收标准（首期）**
1) Paper/Live 均能真实下单并回写成交。
2) 行情来源一致且可追溯。
3) 单实例锁避免重复执行。
4) 风控触发阻断并告警。
5) 批次/订单/成交全链路可审计。

## 10. 实施计划（Phase）
### Phase 1：MVP 真连通
- IB Gateway/TWS systemd 服务
- IBStreamRunner 常驻订阅 + 锁 + 降级
- IBOrderExecutor 真下单与回写
- LiveTrade UI 展示 stream/执行状态

### Phase 2：风险与告警闭环
- 盘中风控定时评估
- 告警与回退机制
- Live 二次确认与高风险操作保护

### Phase 3：调度与体验优化
- 周一调仓调度器
- 幂等与失败重试策略
- 指标与日志完善

## 11. 里程碑与依赖
- 依赖：IB Gateway/TWS 可用、IB API 稳定；Telegram bot 准备好。
- 里程碑：
  - M1：Paper/Live 下单与回写成功
  - M2：风控触发+告警可见
  - M3：自动化调度可运行

