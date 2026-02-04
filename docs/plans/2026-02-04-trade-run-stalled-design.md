# 实盘交易停滞（15 分钟）处理设计

## 背景
实盘交易 run（如 1028）长期处于 running 且无进展，当前页面无法明确区分“正常运行”与“卡住”，导致操作不确定、审计不清晰。

## 目标
- 定义 15 分钟无进展的“停滞（stalled）”规则。
- 明确状态与原因可审计、可解释。
- 提供安全的自动处理与人工处置入口。

## 方案
### 状态与字段
在 `trade_runs` 增加进度字段：
- `last_progress_at`（datetime）
- `progress_stage`（varchar）
- `progress_reason`（text）
- `stalled_at`（datetime）
- `stalled_reason`（text）

新增状态：`stalled`（可选扩展 `waiting_external`）。

### 判定规则
当 `run.status == running` 且满足：
- `now - last_progress_at >= 15min`
- **交易时段内**
则标记 `stalled`，并写入 `stalled_at/stalled_reason`。

### 自动处理
- **不撤单**，仅暂停后续下单。
- 记录审计事件：`trade.run.stalled`，detail 包含 run_id、stage、last_progress_at。

### 人工处置
提供 API：
- `resume`：恢复 running（记录原因）
- `terminate`：终止（failed/canceled）
- `sync`：仅重新同步状态

### 可视化
运行详情显示：
- `last_progress_at` / `progress_stage` / `stalled_reason`
- “停滞时长”与按钮：继续、同步、终止

## 验收标准
- 15 分钟无进展自动标记 `stalled`。
- 页面清晰展示停滞原因与时间。
- 人工操作可追溯、可审计。
