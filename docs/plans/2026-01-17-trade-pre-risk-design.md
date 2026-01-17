# Phase 3.1 预交易风控设计（全局默认 + 单次覆盖）

## 背景与目标
本设计用于完善 IBAutoTrade Phase 3.1（预交易风控），采用 **全局默认 + 单次执行覆盖** 模式（A‑1）。目标是在下单前执行统一、可审计的风控校验：**通过则继续执行，失败则阻断并记录**，保证风控来源清晰、可复现。

## 核心原则
- **单一来源优先级**：`risk_overrides` 覆盖 `risk_defaults`，合并结果写入 `risk_effective`。
- **阻断优先**：任一阈值触发立即阻断，不产生任何下单行为。
- **审计与复现**：每次执行保留“本次有效风控参数 + 触发原因”。

## 数据模型
### 新增配置（建议）
- `trade_settings`（新表）
  - `id`
  - `risk_defaults` JSON（全局风控默认值）
  - `updated_at`
  - API：`GET /api/trade/settings`、`POST /api/trade/settings`

### 运行记录
- `trade_runs.params` 追加：
  - `risk_overrides`（可选，运行时覆盖）
  - `risk_effective`（合并后的最终参数）
  - `risk_blocked`（触发原因与数量）

## 风控项（最小集）
- `portfolio_value`：组合净值（必填，影响比例类判断）
- `cash_available`：可用现金
- `max_order_notional`：单笔订单金额上限
- `max_position_ratio`：单标的最大仓位比例
- `max_total_notional`：当次下单总金额上限
- `max_symbols`：单次订单数量上限
- `min_cash_buffer_ratio`：最小现金缓冲比例（如 5%）

## 执行流程
1. 读取 `risk_defaults`（全局）
2. 合并 `risk_overrides` → 得到 `risk_effective`
3. 生成订单列表后，执行风险校验
4. 若失败：
   - `trade_run.status = blocked`
   - `trade_run.message` 写入首要原因（如 `risk:max_order_notional`）
   - `trade_run.params.risk_blocked` 记录 `{reasons, blocked_count, risk_effective}`
   - **直接退出，不下单**
5. 若通过：进入下单流程

## 错误处理与边界
- 缺失关键输入（如 `portfolio_value` 为空且需要比例判断）→ 直接阻断并提示缺失字段。
- 阈值格式错误（非数值）→ 视为无效并阻断，提示格式问题。

## UI/展示要求
- 展示“全局默认值 + 本次覆盖值 + 最终生效值”。
- 阻断时清晰展示触发原因与被阻断订单数量。

## 测试范围（TDD）
- `max_order_notional` 超限 → 阻断
- `max_position_ratio` 超限 → 阻断
- `max_total_notional` 超限 → 阻断
- `min_cash_buffer_ratio` 违规 → 阻断
- 缺失 `portfolio_value` 但需要比例判断 → 阻断
- 覆盖参数优先级：`overrides` > `defaults`

## 非目标
- 盘中风控（Phase 3.2）
- 回退机制（Phase 3.3）
