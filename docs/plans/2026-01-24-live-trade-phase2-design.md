# 实盘交易 Phase 2（订单与执行）设计方案

**目标**：在现有 IB 连接与数据接入基础上，完成 Paper + Live 共用的一套订单执行闭环（仅 MKT），具备幂等、可追溯与可恢复的执行链路。

## 已确认的约束
- 运行模式：Paper + Live 同链路；Live 需 UI 二次确认（输入固定口令，如 “LIVE”）。
- 首期订单类型：仅 MKT。
- 股数规则：权重→市值→股数 **四舍五入**，不足 1 股直接跳过。
- 并发策略：**全并发**提交订单。
- 数据源：交易行情与执行数据来自 IB（训练/回测不变）。

## 架构概览
- **生成层**：创建 `trade_run` 与 `trade_orders`，并记录参数与信号快照。
- **执行层**：执行器并发提交 `NEW` 状态订单，推进订单状态机并写回 DB。
- **幂等保障**：运行批次与订单级幂等；重复触发不产生重复订单。
- **单实例锁**：执行器入口处校验，避免多副本重复下单。

## 数据模型（新增/完善）
### trade_runs
- 字段建议：
  - `id` (PK)
  - `project_id`
  - `mode` (paper/live)
  - `decision_snapshot_id`
  - `status` (NEW/RUNNING/COMPLETED/FAILED/CANCELED)
  - `requested_at`, `started_at`, `finished_at`
  - `created_by` (UI/调度器/系统)
  - `params` (风控/策略参数快照)

### trade_orders
- 字段建议：
  - `id` (PK)
  - `trade_run_id` (FK)
  - `symbol`
  - `target_weight`, `target_value`
  - `qty` (四舍五入后的股数)
  - `side` (BUY/SELL)
  - `order_type` (MKT)
  - `client_order_id` (幂等键)
  - `ib_order_id`
  - `status` (NEW/SUBMITTED/PARTIAL/FILLED/CANCELED/REJECTED)
  - `error`
  - `submitted_at`, `updated_at`

### trade_fills
- 字段建议：
  - `id` (PK)
  - `trade_order_id` (FK)
  - `fill_qty`, `fill_price`
  - `fill_time`
  - `commission`, `liquidity`

> 数据库变更必须通过脚本：`deploy/mysql/patches/YYYYMMDD_<desc>.sql`，包含变更说明/回滚指引/幂等。

## 状态机
### 订单级
`NEW → SUBMITTED → PARTIAL → FILLED / CANCELED / REJECTED`

### 批次级
`NEW → RUNNING → COMPLETED / FAILED / CANCELED`
- 批次失败不回滚已成交订单。

## API 设计
- `POST /api/trade/runs`
  - 创建批次与订单（可选 `execute=true/false`）
  - Live 需 `live_confirm_token`
- `POST /api/trade/runs/{id}/execute`
  - 启动执行器并发下单
- `GET /api/trade/runs/{id}`
  - 查询批次状态
- `GET /api/trade/orders?run_id=`
  - 查询订单明细与状态

## 幂等策略
- 批次幂等：`project_id + decision_snapshot_id + mode + trade_date` 作为唯一约束或逻辑唯一。
- 订单幂等：`client_order_id = hash(trade_run_id + symbol + side)`。
- 若 `ib_order_id` 已存在，则不重复下单。

## 并发策略
- 执行器对 `NEW` 订单 **全并发**提交。
- 下单请求使用短时锁（`ib_request_lock`）保证串行化 IB 请求；不在等待成交阶段持锁。

## Live 安全确认
- UI 弹窗二次确认 + 输入固定口令。
- 后端必须校验 `live_confirm_token`，否则拒绝执行。

## 最小风控前置（Phase 2）
- 可用资金 ≥ 最小可执行金额
- 单票权重上限
- 最大持仓数上限
- 失败时阻断生成订单并记录审计

## 失败处理
- 下单失败 → 订单 `REJECTED` + 记录 `error`。
- 批次失败 → `trade_run` 标记 `FAILED`。
- 重试策略：人工触发新批次（避免自动重复下单）。

## 测试与验收
### TDD 核心用例
- 批次幂等：同一参数重复创建返回已有 `trade_run`。
- 订单生成：四舍五入、不足 1 股跳过。
- 执行器：`NEW` → `SUBMITTED`；重复执行不生成新 `ib_order_id`。
- Live 口令：缺失/错误应拒绝。

### 验收标准
1) Paper/Live 同流程，订单与成交可追溯。
2) 重复触发不重复下单。
3) UI 可查看批次与订单状态。
4) 失败可审计与人工重试。
