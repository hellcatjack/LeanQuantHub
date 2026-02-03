# 实盘监控 NEW 订单自动处置设计

## 背景
实盘监控中存在大量 NEW 状态订单未及时完成，导致交易队列堆积、风险不可控、人工介入成本高。

## 目标
- 对 NEW 状态订单进行自动处置：超时撤单 + 条件满足时自动重下。
- 过程可审计、可追溯、可配置、可停止。
- 不影响既有风控与交易守卫逻辑。

## 非目标
- 不做复杂的多策略拆单/智能执行。
- 不改动 Lean bridge 输出协议与现有报价逻辑。

## 核心策略
**双阶段策略：**
1) 超时检测 -> 自动撤单
2) 撤单成功后，若仍需成交 -> 自动重下（刷新价格/有效期）

## 规则细节
### 触发条件
- 订单状态为 NEW
- `now - created_at > new_timeout_seconds`
- `filled_quantity == 0`
- 交易守卫未处于 halted/blocked

### 处置步骤
1) 标记 `auto_recovery_requested`
2) 发起撤单请求
3) 撤单成功后评估是否重下
4) 满足重下条件则生成替代订单并提交

### 重下条件
- 未超过最大重试次数
- 最新价偏离不超过阈值
- 当前时间处于允许交易窗口

### 边界处理
- **部分成交**：仅撤单，不自动重下
- **撤单失败/超时**：标记 `recovery_failed` 并记录原因
- **价格偏离过大**：终止自动重下
- **交易窗口外**：仅撤单，不重下

## 配置参数
- `new_timeout_seconds` (默认 45s)
- `max_auto_retries` (默认 1)
- `max_price_deviation_pct` (默认 1.5%)
- `allow_replace_outside_rth` (默认 false)

## 数据结构与状态扩展
建议在 `trade_orders.params` 中记录自动处置字段：
- `auto_recovery_requested_at`
- `auto_recovery_attempts`
- `auto_recovery_last_reason`
- `auto_recovery_last_action` (cancel/replace/stop)

## 可审计性
每次自动处置必须写 `audit_logs`：
- 原订单 ID、触发阈值、触发时间
- 撤单结果、替代订单 ID
- 失败原因或终止原因

## 模块落地（建议）
- `trade_order_recovery.py`：扫描 NEW 订单并触发处置
- 复用既有撤单与下单执行逻辑
- 可通过定时任务或接口触发

## 前端展示
- 实盘监控增加“自动处置摘要”
- 订单列表展示自动处置标记与原因

## 验收标准
- TWS 未连接时不会进入重下流程
- 超时 NEW 订单能够被撤单
- 满足条件时可成功自动重下
- 所有步骤具备审计日志
