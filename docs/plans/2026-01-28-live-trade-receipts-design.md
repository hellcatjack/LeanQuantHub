# 实盘监控回执（订单提交/成交）设计

日期：2026-01-28

## 背景与目标
实盘交易页面底部“实盘监控”需要新增“订单提交/成交回执”视图，统一展示订单提交、成交等回执事件，并与现有“订单/成交”列表并列显示，便于定位交易链路与来源。

## 范围
- 新增后端回执接口，合并 DB 订单/成交与 Lean 直连执行日志。
- 前端新增“回执”Tab，支持分页（默认 50 条）。
- i18n 文案同步（中英文）。

不在本次范围：持久化回执表、复杂告警/订阅、历史批量导入。

## 数据源与合并规则
- **DB 主来源**：trade_orders + fills（已有订单/成交数据）。
- **Lean 直连日志**：`{data_root}/lean_bridge/**/execution_events.jsonl`。
- 合并顺序：先加载 DB 回执，再加载 Lean 回执并去重。
- 去重策略：优先以 `client_order_id + exec_id + kind + time` 组合键去重；若 DB 已存在成交明细（exec_id/time/qty/price），则忽略 Lean 的同一成交事件。
- 排序：按 `time` 倒序。

## API 设计
- `GET /api/trade/receipts?limit=50&offset=0&mode=all`
- `mode`：`all|orders|fills`（可选，便于调试/扩展）。
- 响应：
  - `items`: 回执数组（按时间倒序）
  - `total`: 总数
  - Header: `X-Total-Count`
- 回执字段（示例）：
  - `time`, `kind`, `order_id`, `client_order_id`, `symbol`, `side`,
    `quantity`, `filled_quantity`, `fill_price`, `exec_id`, `status`, `source`

## 前端展示
- “实盘监控”新增 **回执** Tab。
- 表格列：时间、类型、订单ID、客户端订单ID、标的、方向、数量、成交量、成交价、状态、来源。
- 默认分页：50 条，使用现有分页组件。
- 错误仅在“回执”区域提示，不影响其他 Tab。

## 错误处理
- `limit/offset/mode` 非法返回 422。
- Lean 日志缺失/解析失败：记录 warning，接口仍返回 200，并在响应中附带 `warnings`（数组）提示。

## 测试策略（TDD）
- 后端单测：构造临时 data_root 与伪 `execution_events.jsonl`，验证合并顺序、去重、warnings 行为。
- 前端 Playwright：mock `/api/trade/receipts`，验证回执 Tab 渲染与分页；补充 Lean 日志缺失情况下的提示渲染。

## 验收标准
- 回执 Tab 可展示订单提交/成交回执，排序正确。
- Lean 日志异常不影响 DB 回执展示。
- i18n 文案完整（中英文）。
- 新增测试通过，且不会影响现有订单/成交功能。

## 风险与后续
- Lean 日志格式变化会影响解析：需要警告可观测性。
- 若后续回执量增大，可考虑持久化回执表或按日期分片读取。
