# 实盘回执写回 DB 设计（请求时即时写回）

日期：2026-01-28

## 背景
目前实盘监控回执可展示 Lean 回执事件，但订单明细仍停留在 NEW 状态，原因是回执未写回数据库。本方案在调用 `/api/trade/receipts` 时即时写回 DB，使订单状态与成交记录与回执保持一致。

## 目标
- 回执请求触发写回，订单状态与成交记录在 DB 中同步更新。
- 写回幂等，多次刷新不重复生成成交。
- 单条事件失败不影响整体回执返回。

## 数据源与事件映射
- 数据源：`{data_root}/lean_bridge/**/execution_events.jsonl`。
- 订单定位：优先使用目录名 `direct_{order_id}`；若无法解析，则尝试从 `tag` 解析 `direct:{order_id}`；无法定位则跳过并记录 warning。
- 事件映射：
  - `Submitted/New` → 订单状态更新为 `SUBMITTED`
  - `PartiallyFilled/Partial` → 生成成交 + 状态 `PARTIAL`
  - `Filled` → 生成成交 + 状态 `FILLED`
  - `Canceled/Cancelled` → 状态 `CANCELED`
  - `Rejected/Invalid` → 状态 `REJECTED`，记录 `params.reason`

## 写回幂等策略
- 成交去重键：`order_id + filled + fill_price + time`。
- 在 `TradeFill.params` 写入 `event_time`、`event_source=lean`、`event_tag`（若有），重复请求可通过 event_time 判重。
- 订单状态更新遵循 `ALLOWED_TRANSITIONS`，非法跃迁记录 warning 并跳过。

## 接口流程
`/api/trade/receipts`：
1) 读取 Lean 回执事件并写回 DB（尽力而为）。
2) 基于写回后的 DB 生成回执列表。
3) 返回 `items/total/warnings`，并设置 `X-Total-Count`。

## 错误处理
- Lean 日志缺失/解析错误：记录 warnings，不阻断接口。
- 订单不存在/解析失败：记录 warnings，继续处理。
- 单条事件失败不影响其它事件处理。

## 测试策略（TDD）
- 单测：
  - 正常写回：NEW → SUBMITTED → FILLED，成交写入且幂等。
  - REJECT/CANCEL 状态写回。
  - 订单不存在/非法状态跃迁生成 warnings。
- 接口测试：`/api/trade/receipts` 返回写回后的订单/成交与正确分页头。
- 现有 Playwright 回执 UI 测试回归。

## 验收标准
- `/api/trade/receipts` 后订单明细状态与回执一致。
- 多次刷新不重复产生成交。
- 回执接口可用且不因单条事件失败而 500。
