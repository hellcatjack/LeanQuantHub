# IB 交易执行闭环设计（首期：Paper + Live）

日期：2026-01-23

## 目标
构建“手动触发”的交易执行闭环，支持 Paper + Live，订单类型仅 MKT，且**必须回写成交回报（fills）**，与现有决策快照联动形成可追溯链路。

## 范围与约束
- 触发方式：仅手动触发（API/界面按钮）。
- 订单类型：仅 MKT。
- 模式：Paper + Live。
- 必须回写成交回报（fills），并支持幂等重试。
- 单实例执行：复用现有锁与 guard，避免并发下单。

## 方案选择
**推荐方案：同步执行 + 回报监听线程（单进程）**
- API 触发后在同进程完成下单与回报监听。
- 优点：实现快、流程可控、便于单实例锁；适合首期手动触发。
- 风险：调用时间长，需要明确超时与降级策略。

## 架构与数据流（简述）
1) 前端触发执行 → 后端 `trade_executor` 读取 `decision_snapshot_id`。
2) 生成订单草稿（权重→目标市值→股数）并校验资金/参数。
3) 建立 IB 连接（Paper/Live 取决于 `trade_run.mode`），逐笔发送 MKT 订单。
4) 启动回报监听线程，接收 `orderStatus/execDetails` 并回写 DB。
5) 汇总 run 状态（全部 FILLED / 部分 / 失败）并返回。

## 订单状态机与幂等
- 状态机：`NEW → SUBMITTED → PARTIAL → FILLED / CANCELED / REJECTED`。
- client_order_id：由 `run_id + decision_snapshot_id + symbol + side` 组合。
- 幂等策略：
  - 相同 client_order_id 已存在则复用，不重复下单。
  - 成交回报按 exec_id 或 IB orderId 去重落库。
  - run 若已 `executing/success/failed`，重复触发只返回现有结果。

## 错误处理与超时
- 连接失败：run 标记 `failed`，不创建订单。
- 下单失败：订单标记 `REJECTED`，run 汇总为 `failed/partial_failed`。
- 回报超时：run 标记 `degraded`，提供“继续监听/手动刷新”入口。
- Live 模式：强制二次确认（前端确认 + 服务端 guard）。

## 数据库与接口改动
### DB 变更
- 新增 `trade_fills` 表：
  - `order_id, exec_id, filled_qty, price, commission, trade_time, currency, exchange, raw_payload` 等。
- 扩展 `trade_orders`：
  - `ib_order_id, ib_perm_id, last_status_ts, rejected_reason` 等字段。
- 可选扩展 `trade_runs`：
  - `exec_started_at, exec_ended_at, summary`。

**注意**：所有 DB 变更必须以脚本形式落地，放置于 `deploy/mysql/patches/` 并包含说明/影响/回滚指引。

### 接口建议
- `POST /api/trade/runs/{id}/execute`：扩展回报监听与返回结构。
- `GET /api/trade/runs/{id}/orders`：订单 + fills。
- `GET /api/trade/runs/{id}/fills`（可选）。

## 测试与验收
### 单元测试
- 幂等：重复触发不重复下单。
- 状态机：状态转移正确。
- 回报去重：同 exec_id 不重复写。

### 集成测试
- stub/mock IB 回调，验证订单/回报落库。
- 超时触发 `degraded` 行为。

### 手工验收（Paper）
1) 生成决策快照。
2) 创建 trade_run。
3) 执行 MKT。
4) 校验订单/成交回报。
5) 校验 run 状态与日志。

验收标准：
- 重复触发不重复下单。
- 回报完整、可追溯。
- 连接失败/回报超时有明确状态。
- Live 模式二次确认与配置校验生效。

## 里程碑（建议）
- M1：订单执行 + 回报回写（Paper）。
- M2：Live 模式开关 + 二次确认。
- M3：监控与告警联动（后续）。
