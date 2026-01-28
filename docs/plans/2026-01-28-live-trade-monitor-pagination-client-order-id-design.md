# 实盘监控分页与手工 client_order_id 唯一后缀设计

## 背景
实盘交易页面“实盘监控”订单列表需要分页，默认每页 50 条并支持 50/100/200。当前订单列表来自 `/api/trade/orders`，前端使用 `limit=5`，缺乏总数。与此同时，手工传入的 `client_order_id` 可能过于简单（如仅时间戳），在批量强制平仓时容易触发唯一约束冲突。

## 目标
- 实盘监控订单列表支持分页（页码 + 上/下一页）。
- 默认每页 50 条，可选 50/100/200。
- 后端通过响应头 `X-Total-Count` 返回总数，接口仍为 list 兼容现有调用。
- 手工传入 `client_order_id` 自动追加唯一 suffix，确保“不可能重复”。
- 自动生成的 `client_order_id`（decision_snapshot 等）不被改写。

## 范围
- 后端：`/api/trade/orders` 添加 `X-Total-Count`；订单创建时追加 suffix；新增序列表与迁移脚本。
- 前端：实盘监控订单表引入分页条；固定显示全局订单（不再优先 runDetail.orders）。
- 数据库：新增序列表（独立于 trade_orders）。

## 非目标
- 不改变 `/api/trade/orders` 返回结构（仍为列表）。
- 不对历史订单回溯修复 `client_order_id`。
- 不更改 fills/批次详情分页策略（只覆盖全局订单列表）。

## 方案

### 1) 手工 client_order_id 唯一 suffix
- 新增序列表 `trade_order_client_id_seq`（AUTO_INCREMENT）。
- 创建订单时：若 `client_order_id` 属于“手工来源”，先插入序列表获取 `seq_id`，将 `base36(seq_id)` 作为 suffix。
- 新 ID 格式：`{manualBase}-{base36(seq)}`。
- 判定“手工来源”：`run_id is None` 且 `params.source != "decision_snapshot"` 且 `params.client_order_id_auto != true`。
- 长度限制 64：若超长，截断 `manualBase` 并把原始值写入 `params.original_client_order_id`。

### 2) 实盘监控分页
- `/api/trade/orders` 保持 list 输出，新增 `X-Total-Count`。
- 前端分页状态：`page`, `pageSize`, `total`；`offset=(page-1)*pageSize`。
- UI 使用现有 `PaginationBar` 组件，pageSize 选项为 50/100/200。
- 订单表只显示全局订单 `tradeOrders`（不再使用 `runDetail.orders`）。

## 数据库变更
- 新增脚本：`deploy/mysql/patches/YYYYMMDD_trade_order_client_id_seq.sql`。
- 包含：变更说明、影响范围、回滚指引；幂等（`IF NOT EXISTS`）。

## 错误处理
- 序列表插入失败 → 抛出 `client_order_id_seq_failed`。
- `client_order_id` 仍超长 → 强制截断并记录原值。
- `/api/trade/orders` 无法获取 total → 头部返回 0，列表仍返回。

## 测试与验证
- 后端：
  - 手工 `client_order_id` 会追加 suffix，且全局唯一。
  - 自动来源不会被改写。
  - 超长 ID 被截断并保留原值。
  - `/api/trade/orders` 返回 `X-Total-Count`。
- 前端：
  - 翻页触发正确的 `limit/offset`。
  - 仅展示全局订单。
- 手动：批量手工下单，确认无冲突；页面分页正常。

## 验收标准
- 实盘监控订单列表可分页、默认 50 条、可选 50/100/200。
- `X-Total-Count` 生效，页码与总数正确。
- 手工 `client_order_id` 自动追加唯一 suffix，无冲突。
